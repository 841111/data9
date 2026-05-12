# ============================================================
# services.py — 业务逻辑层
# 作用：把"请求参数"变成"完整业务流程"
#       它调用 face_engine（AI处理）和 database（数据存储），
#       把结果组装成最终响应
# ============================================================

import hashlib    # 计算 MD5 哈希，用于防止重复帧（防录像攻击）
import os         # 获取 CPU 核心数
import time       # 获取当前时间戳
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
# ThreadPoolExecutor：线程池，用于并行处理集体照片中的多张人脸
# TimeoutError：超时异常（Python 内置的被这里重命名了）
from datetime import datetime
from pathlib import Path

import cv2

from .config import API_TIMEOUT_SECONDS, REPORT_DIR, FACE_DB_DIR
from .database import (
    _get_connection, fetch_students, fetch_students_from_face_data,
    insert_activity, insert_activity_with_details,
    insert_attendance, upsert_student, upsert_student_with_details,
)
from .face_engine import (
    analyze_emotion, crop_face_with_margin, decode_base64_image,
    decode_upload_image, detect_faces, face_embedding,
    liveness_check, match_student, preprocess_face_for_emotion,
)
from .models import AttendanceResult, GroupRecognitionItem, GroupRecognitionResponse

# 防录像重放攻击：记录每个课堂最后一帧的哈希值和时间
# key = classroom_id，value = (图片哈希, 时间戳, 模糊度分数)
last_processed_hash: dict[str, tuple[str, float, float]] = {}

# 同一帧在 1 秒内重复提交，视为录像回放，拒绝签到
REPLAY_WINDOW_SECONDS = 1.0

# 全局线程池（用于人脸识别超时控制）
# max_workers=4：最多 4 个并发任务
_timeout_executor = ThreadPoolExecutor(max_workers=4)


def with_timeout(func, *args, **kwargs):
    """
    带超时的函数执行器
    
    把函数提交到线程池，设定最长等待时间
    超时后抛出 TimeoutError，防止用户等太久
    
    *args, **kwargs：把所有参数原样传给目标函数（透传）
    """
    future = _timeout_executor.submit(func, *args, **kwargs)  # 提交任务到线程池
    try:
        # timeout=API_TIMEOUT_SECONDS：最多等这么多秒
        return future.result(timeout=API_TIMEOUT_SECONDS)
    except FuturesTimeoutError as exc:
        # 线程池的超时异常 → 转换成 Python 标准的 TimeoutError
        raise TimeoutError("Recognition timeout") from exc


def _process_single_face(face_data: tuple) -> GroupRecognitionItem | None:
    """
    处理集体照片中单张人脸的完整流程（工作函数，被线程池调用）
    
    流程：裁剪 → 提取特征 → 匹配学生 → 分析情绪 → 记录数据库
    返回 None 表示这张脸没有匹配到学生
    """
    # 从元组中解包参数（因为线程池的 map 只接受单参数）
    image, coords, students, activity_name, activity_type, activity_time = face_data
    x, y, w, h = coords

    try:
        face_region = crop_face_with_margin(image, x, y, w, h)  # 裁剪人脸
        emb = with_timeout(face_embedding, face_region)          # 提取特征（有超时）
        matched = with_timeout(match_student, emb, students)     # 匹配学生（有超时）

        if matched is None:
            return None  # 没有匹配到，跳过

        emotion, emotion_confidence, emotion_source = analyze_emotion(face_region)

        # 记录活动参与数据
        insert_activity_with_details(
            activity_name, activity_type, activity_time,
            matched.student_id, matched.student_name
        )

        return GroupRecognitionItem(
            student_id=matched.student_id,
            student_name=matched.student_name,
            score=matched.score,
            emotion=emotion,
            emotion_confidence=emotion_confidence,
            emotion_source=emotion_source,
        )
    except Exception:
        return None  # 任何异常（包括超时）都不影响其他人脸的处理


# ---- 业务函数 ----

def register_student(student_id: str, name: str, image_base64: str) -> dict:
    """
    注册学生（Base64 图片版）
    
    流程：
    1. 解码图片
    2. 检测人脸（必须恰好一张）
    3. 裁剪并提取人脸特征向量
    4. 存入数据库
    """
    image = decode_base64_image(image_base64)   # Base64 → OpenCV 图片
    faces = detect_faces(image)                  # 检测人脸位置

    # 注册照片要求严格：必须且只能有一张人脸
    if len(faces) != 1:
        raise ValueError("Registration image must contain exactly one face")

    x, y, w, h = faces[0]                         # 取唯一的人脸矩形
    face = crop_face_with_margin(image, x, y, w, h)  # 裁剪人脸区域
    embedding = face_embedding(face)               # 提取 128 维特征向量
    upsert_student(student_id=student_id, name=name, embedding=embedding)  # 存库

    return {"success": True, "student_id": student_id, "name": name}


def check_attendance(classroom_id: str, teacher_name: str, image_base64: str) -> AttendanceResult:
    """
    执行一次签到检查——系统最核心的函数
    
    完整流程：
    1. 基本校验（图片不能为空）
    2. 防录像重放检测（同一帧/同一模糊度短时间重复）
    3. 解码图片，计算模糊度
    4. 检测人脸（必须检测到至少一张）
    5. 提取人脸特征向量
    6. 加载学生数据库（优先从文件，再从 SQLite）
    7. 匹配最相似的学生
    8. 活体检测（防照片欺骗）
    9. 情绪分析
    10. 记录签到日志
    11. 返回结果
    """
    try:
        # ---- 1. 基本校验 ----
        if not image_base64 or len(image_base64) < 100:
            raise ValueError("Camera data is corrupted or empty")

        now_ts = time.time()

        # ---- 2. 防重放：哈希检测 ----
        # MD5 哈希：把图片内容压缩成 32 个十六进制字符的"指纹"
        # 相同内容 → 相同指纹；不同内容 → 不同指纹
        img_hash = hashlib.md5(image_base64.encode("utf-8")).hexdigest()
        previous = last_processed_hash.get(classroom_id)  # 取上次记录

        if previous is not None:
            previous_hash, previous_ts, previous_blur_score = previous
            # 如果 1 秒内提交了哈希值完全相同的图片 → 录像回放
            if now_ts - previous_ts <= REPLAY_WINDOW_SECONDS and previous_hash == img_hash:
                time_value = insert_attendance(
                    classroom_id=classroom_id, teacher_name=teacher_name,
                    success=False, reason="Duplicate frame detected",
                    liveness_passed=False, emotion="unknown",
                )
                return AttendanceResult(
                    success=False, reason="Duplicate frame detected",
                    liveness_passed=False, emotion="unknown",
                    attendance_time=time_value,
                )

        # ---- 3. 解码 + 模糊度 ----
        image = decode_base64_image(image_base64)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Laplacian 方差 = 图片清晰度指标
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        if previous is not None:
            previous_hash, previous_ts, previous_blur_score = previous
            # 防重放第二重：不同帧但模糊度几乎一样（1e-6 精度），可能是截帧攻击
            if (
                now_ts - previous_ts <= REPLAY_WINDOW_SECONDS
                and abs(blur_score - previous_blur_score) < 1e-6
            ):
                time_value = insert_attendance(
                    classroom_id=classroom_id, teacher_name=teacher_name,
                    success=False, reason="Suspicious replay pattern detected",
                    liveness_passed=False, emotion="unknown",
                )
                return AttendanceResult(
                    success=False, reason="Suspicious replay pattern detected",
                    liveness_passed=False, emotion="unknown", attendance_time=time_value,
                )

        # 更新当前帧记录
        last_processed_hash[classroom_id] = (img_hash, now_ts, blur_score)

        # ---- 4. 人脸检测 ----
        faces = detect_faces(image)
        if len(faces) == 0:
            time_value = insert_attendance(
                classroom_id=classroom_id, teacher_name=teacher_name,
                success=False, reason="No face detected",
                liveness_passed=False, emotion="unknown",
            )
            return AttendanceResult(
                success=False, reason="No face detected",
                liveness_passed=False, emotion="unknown", attendance_time=time_value,
            )

        # ---- 5. 提取特征 ----
        x, y, w, h = faces[0]  # 只处理第一张脸
        face = crop_face_with_margin(image, x, y, w, h)
        face = preprocess_face_for_emotion(face)  # 预处理（提升精度）
        emb = with_timeout(face_embedding, face)  # 提取特征（有超时保护）

        # ---- 6. 加载学生数据库 ----
        # 优先从文件系统加载（含实时注册的照片），文件系统为空再查 SQLite
        students = fetch_students_from_face_data()
        if not students:
            students = fetch_students()

        # 调试用：计算与所有学生的距离，返回给前端
        from .face_engine import embedding_distance
        debug_scores = [
            (s["student_id"], float(embedding_distance(emb, s["embedding"])))
            for s in students
        ]

        # ---- 7. 匹配 + 8. 活体 + 9. 情绪 ----
        matched = with_timeout(match_student, emb, students)
        liveness_passed, liveness_message = liveness_check(face)
        emotion, emotion_confidence, emotion_source = analyze_emotion(face)

        # 活体未通过时直接拒绝签到，避免照片/屏幕帧被记为成功。
        if not liveness_passed:
            reason = f"Liveness check failed: {liveness_message}"
            time_value = insert_attendance(
                classroom_id=classroom_id, teacher_name=teacher_name,
                success=False, reason=reason,
                liveness_passed=False, emotion=emotion,
            )
            return AttendanceResult(
                success=False, reason=reason,
                liveness_passed=False, emotion=emotion,
                emotion_confidence=emotion_confidence, emotion_source=emotion_source,
                debug_scores=debug_scores, attendance_time=time_value,
            )

        # ---- 10-11. 记录并返回 ----
        if matched is None:
            reason = "No matched student - Please register first"
            time_value = insert_attendance(
                classroom_id=classroom_id, teacher_name=teacher_name,
                success=False, reason=reason,
                liveness_passed=liveness_passed, emotion=emotion,
            )
            return AttendanceResult(
                success=False, reason=reason,
                liveness_passed=liveness_passed, emotion=emotion,
                emotion_confidence=emotion_confidence, emotion_source=emotion_source,
                debug_scores=debug_scores, attendance_time=time_value,
            )

        # 匹配成功且活体通过，才允许签到成功
        reason = "Attendance success"
        time_value = insert_attendance(
            classroom_id=classroom_id, teacher_name=teacher_name,
            success=True, reason=reason,
            student_id=matched.student_id, student_name=matched.student_name,
            score=matched.score, liveness_passed=liveness_passed, emotion=emotion,
        )
        return AttendanceResult(
            success=True, reason=reason,
            student_id=matched.student_id, student_name=matched.student_name,
            score=matched.score, liveness_passed=liveness_passed, emotion=emotion,
            emotion_confidence=emotion_confidence, emotion_source=emotion_source,
            debug_scores=debug_scores, attendance_time=time_value,
        )

    except ValueError as exc:
        # 已知错误（如图片损坏）→ 返回失败结果（不崩溃）
        return AttendanceResult(
            success=False, reason=f"Device Error: {str(exc)}",
            liveness_passed=False, emotion="unknown",
        )
    except TimeoutError:
        # 超时 → 返回失败结果
        return AttendanceResult(
            success=False, reason="System busy, please try again",
            liveness_passed=False, emotion="unknown",
        )


def recognize_group_photo(
    activity_name: str,
    raw: bytes,
    activity_type: str = "other",
    activity_time: str | None = None,
) -> GroupRecognitionResponse:
    """
    集体照片识别——并行处理版
    
    对照片中的每张脸独立处理（特征提取、匹配、情绪分析）
    使用线程池并行，利用多核 CPU 加速
    """
    image = decode_upload_image(raw)   # 解码上传的图片文件
    faces = detect_faces(image)         # 检测所有人脸

    # 加载学生数据库
    students = fetch_students_from_face_data()
    if not students:
        students = fetch_students()

    if not faces:  # 没有检测到人脸
        return GroupRecognitionResponse(
            success=True, total_faces=0, matched_count=0, matched_students=[],
        )

    # 把每张脸的处理参数打包成元组列表（供线程池使用）
    task_data = [
        (image, face_coords, students, activity_name, activity_type, activity_time)
        for face_coords in faces
    ]

    # 动态计算线程数：CPU 核心数 × 2，但不超过 8 或人脸数
    worker_target = (os.cpu_count() or 1) * 2
    max_workers = max(1, min(len(faces), worker_target, 8))

    # executor.map：把 task_data 中每个元素分别传给 _process_single_face 并行执行
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_process_single_face, task_data))

    # 过滤掉 None（没有匹配到学生的人脸）
    matched_items = [item for item in results if item is not None]

    return GroupRecognitionResponse(
        success=True,
        total_faces=len(faces),
        matched_count=len(matched_items),
        matched_students=matched_items,
    )


def export_attendance_to_excel() -> str:
    """
    把签到记录导出为 Excel 文件
    
    pandas + openpyxl 组合：
    - pandas 从 SQLite 读取数据 → DataFrame（表格对象）
    - openpyxl 把 DataFrame 写成 .xlsx 文件
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise ValueError("pandas not installed. Run: pip install pandas openpyxl") from exc
    
    try:
        import openpyxl  # noqa: F401 (explicit check to ensure it's available)
    except ImportError as exc:
        raise ValueError("openpyxl not installed. Run: pip install pandas openpyxl") from exc

    try:
        conn = _get_connection()
        # read_sql_query：直接把 SQL 查询结果变成 DataFrame
        df = pd.read_sql_query("SELECT * FROM attendance", conn)
        
        if df.empty:
            raise ValueError("No attendance records found in database")

        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        # 文件名包含时间戳，避免覆盖
        file_path = REPORT_DIR / f"attendance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        # to_excel：DataFrame → Excel 文件，index=False 不写行号列
        df.to_excel(file_path, index=False, engine='openpyxl')
        return str(file_path)
    except Exception as exc:
        raise ValueError(f"Excel export failed: {str(exc)}") from exc


def register_student_with_photo(
    student_id: str,
    student_name: str,
    major: str,
    gender: str,
    image_data: bytes,
) -> dict:
    """
    注册学生（文件上传版）
    
    除了存数据库，还把裁剪好的人脸图片存到 FACE_DB_DIR
    文件名格式：{学号}-{姓名}-{专业}-{性别}.jpg
    这样 fetch_students_from_face_data() 可以直接从文件恢复数据
    """
    image = decode_upload_image(image_data)  # bytes → OpenCV 图片
    faces = detect_faces(image)

    if len(faces) == 0:
        raise ValueError("未检测到人脸，请确保照片中只有一个人脸且光线充足")
    elif len(faces) > 1:
        raise ValueError("检测到多个人脸，请确保照片中只有一个人脸")

    x, y, w, h = faces[0]
    face = crop_face_with_margin(image, x, y, w, h)
    embedding = face_embedding(face)

    # 同时存 SQLite 和文件系统（双备份，互为冗余）
    upsert_student_with_details(student_id, student_name, major, gender, embedding)

    FACE_DB_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{student_id}-{student_name}-{major}-{gender}.jpg"
    file_path = FACE_DB_DIR / filename

    # Windows 下 cv2.imwrite 对中文路径不稳定，改为先编码再由 Python 写入磁盘。
    # face 此处是 OpenCV 的 BGR 图像，直接编码为 JPEG 即可。
    success, buffer = cv2.imencode(".jpg", face)
    if not success:
        raise ValueError(f"Failed to encode face image for {file_path}")

    file_path.write_bytes(buffer.tobytes())
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise ValueError(f"Failed to save face image to {file_path}")

    return {
        "success": True,
        "student_id": student_id,
        "student_name": student_name,
        "file_path": str(file_path),
        "saved": True,
        "save_message": "Face image saved successfully",
    }
