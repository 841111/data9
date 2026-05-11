# ============================================================
# face_engine.py — 人脸识别引擎
# 作用：所有与人脸相关的 AI/CV 算法都在这里
#       包括：图片解码、人脸检测、特征提取、匹配、活体检测、情绪分析
# ============================================================

import base64      # 把 Base64 字符串解码成二进制图片数据
import hashlib     # 计算哈希值（用于不同长度向量的比较场景）
import io          # 内存中的字节流（不需要先保存到文件）
from dataclasses import dataclass  # 装饰器，用来快速定义数据类

import cv2         # OpenCV：计算机视觉库，图片处理的核心工具
import numpy as np # NumPy：数值计算库，矩阵运算、向量计算
from PIL import Image  # Pillow：图片格式转换（JPEG/PNG → numpy array）

from .config import MAX_IMAGE_SIZE_MB

# 尝试导入高精度人脸识别库（依赖 dlib，安装复杂）
# 如果没有安装，face_recognition = None，后续用 OpenCV 降级处理
try:
    import face_recognition  # type: ignore  # 忽略类型检查警告
except Exception:
    face_recognition = None  # 降级标记


# ---- 数据类 ----

@dataclass  # 自动生成 __init__、__repr__ 等方法
class FaceMatch:
    """封装人脸匹配结果的数据类"""
    student_id: str    # 匹配到的学生学号
    student_name: str  # 匹配到的学生姓名
    score: float       # 匹配距离（越小越相似）


# ============================================================
# 图片解码函数
# ============================================================

def decode_base64_image(image_base64: str) -> np.ndarray:
    """
    把前端传来的 Base64 字符串解码成 OpenCV 图片（numpy 数组）
    
    Base64 原理：
      二进制图片 → 每3个字节 → 4个可打印字符
      "data:image/jpeg;base64,/9j/4AAQ..." 这种格式
    
    OpenCV 使用 BGR 颜色通道顺序（不是常见的 RGB）
    """
    # 如果有 "data:image/jpeg;base64," 这样的前缀，把逗号前的部分去掉
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]  # 只保留逗号后面的纯 Base64 数据

    # base64.b64decode：把 Base64 字符串 → 原始二进制字节
    raw = base64.b64decode(image_base64, validate=True)

    # 检查大小，防止超大图片耗尽服务器内存
    if len(raw) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise ValueError("Image too large")

    # io.BytesIO：把字节数据包装成"文件对象"，PIL 可以直接从中读取图片
    # .convert("RGB")：统一转成 RGB 格式（去掉 Alpha 透明通道等）
    image = Image.open(io.BytesIO(raw)).convert("RGB")

    # cv2.cvtColor + COLOR_RGB2BGR：把 PIL 的 RGB 数组转成 OpenCV 的 BGR 格式
    # np.array(image)：PIL Image → numpy 数组（形状：H × W × 3）
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def decode_upload_image(raw: bytes) -> np.ndarray:
    """
    把上传的原始字节数据解码成 OpenCV 图片（适用于文件上传接口）
    逻辑同 decode_base64_image，只是输入已经是 bytes，不需要 Base64 解码
    """
    if len(raw) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise ValueError("Image too large")
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


# ============================================================
# 人脸检测
# ============================================================

def detect_faces(image: np.ndarray) -> list[tuple[int, int, int, int]]:
    """
    在图片中检测所有人脸，返回每张脸的矩形位置
    
    使用 Haar 级联分类器（传统机器学习方法，速度快）：
    原理：用大量正样本（有脸）和负样本（无脸）训练的分类器，
         用滑动窗口扫描图片，快速判断每个区域是否含有人脸
    
    返回：[(x, y, w, h), ...]
          x, y = 人脸矩形左上角坐标
          w, h = 宽度和高度
    """
    # 转灰度图：Haar 分类器在灰度图上工作，减少计算量
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 加载 OpenCV 内置的正面人脸检测器（XML 文件存储训练好的模型参数）
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    # detectMultiScale：在不同尺度（大小）下检测人脸
    # scaleFactor=1.1：每次缩放比例（1.1 表示缩小 10%，检测不同大小的脸）
    # minNeighbors=5：候选矩形需要被至少 5 个相邻矩形确认才算真正的脸（减少误检）
    # minSize=(60,60)：忽略小于 60×60 像素的人脸（过小的不可靠）
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))

    # int() 转换确保返回 Python 原生 int，而不是 numpy.int64
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]


def crop_face_with_margin(
    image: np.ndarray, x: int, y: int, w: int, h: int, margin_ratio: float = 0.22
) -> np.ndarray:
    """
    在检测到的人脸矩形外扩展一定比例的边距后裁剪
    
    为什么要扩边？因为 Haar 检测到的矩形通常只包含核心面部，
    扩边后包含更多上下文（发型、脖子），提升特征提取精度
    
    margin_ratio=0.22：上下左右各扩展 22% 的边长
    """
    ih, iw = image.shape[:2]  # image.shape = (高度, 宽度, 颜色通道数)，[:2] 取前两个

    dx = int(w * margin_ratio)  # 水平扩展量（像素）
    dy = int(h * margin_ratio)  # 垂直扩展量（像素）

    # max(0, ...)：防止坐标超出图片左/上边界变成负数
    x1 = max(0, x - dx)
    y1 = max(0, y - dy)

    # min(iw/ih, ...)：防止坐标超出图片右/下边界
    x2 = min(iw, x + w + dx)
    y2 = min(ih, y + h + dy)

    # NumPy 切片裁剪：image[y1:y2, x1:x2] 取矩形区域（注意 y 在前）
    return image[y1:y2, x1:x2]


# ============================================================
# 人脸特征提取（Embedding）
# ============================================================

def _fallback_embedding(face_region: np.ndarray) -> list[float]:
    """
    降级方案：用颜色直方图生成人脸特征向量（无需 face_recognition 库）
    
    原理：把人脸灰度图的像素值分布（直方图）当作特征
    缺点：精度远低于深度学习方法，但无需 GPU，随时可用
    
    返回：长度 32 的归一化向量
    """
    # 转灰度图并缩放到固定大小（消除分辨率差异的影响）
    gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (48, 48))  # 统一缩放到 48×48

    # 计算灰度直方图：把 0-255 的像素值分成 32 个区间（bins）
    hist = cv2.calcHist([resized], [0], None, [32], [0, 256]).flatten()

    # 归一化：除以向量的模（L2 范数），使向量长度为 1
    # 归一化后不同图片的直方图可以公平比较（消除亮度差异）
    # 1e-8：防止除以 0
    hist = hist / (np.linalg.norm(hist) + 1e-8)

    return hist.astype(np.float32).tolist()  # 转为 Python list 方便 JSON 存储


def face_embedding(face_region: np.ndarray) -> list[float]:
    """
    提取人脸特征向量（Embedding）——核心函数
    
    什么是 Embedding（嵌入）？
    把一张人脸图片压缩成一个固定长度的数字向量（如 128 维）
    相同的人 → 向量距离近；不同的人 → 向量距离远
    
    优先使用深度学习方法（face_recognition），
    不可用时降级到直方图方法
    """
    if face_recognition is not None:  # 高精度模式
        # face_recognition 需要 RGB 格式（OpenCV 默认 BGR，需要转换）
        rgb = cv2.cvtColor(face_region, cv2.COLOR_BGR2RGB)

        # face_encodings：深度学习模型提取 128 维特征向量
        # 返回列表（因为可能有多张脸），取第一个
        enc = face_recognition.face_encodings(rgb)
        if enc:
            return enc[0].astype(np.float32).tolist()

    # 降级：高精度库不可用，或图片中没有检测到人脸
    return _fallback_embedding(face_region)


# ============================================================
# 人脸匹配
# ============================================================

def embedding_distance(a: list[float], b: list[float]) -> float:
    """
    计算两个特征向量之间的欧氏距离
    
    欧氏距离公式：sqrt(sum((a[i] - b[i])^2))
    距离越小 = 两张脸越相似
    
    如果两个向量长度不同（说明用了不同的特征提取方法），
    则用哈希值生成等长向量再比较（兜底策略）
    """
    aa = np.array(a, dtype=np.float32)
    bb = np.array(b, dtype=np.float32)

    if aa.shape != bb.shape:
        # 不同长度的向量不能直接计算距离
        # 通过哈希把两个向量都映射成 32 维向量再比较
        seed_a = hashlib.sha256(aa.tobytes()).digest()  # 32 字节
        seed_b = hashlib.sha256(bb.tobytes()).digest()
        aa = np.frombuffer(seed_a, dtype=np.uint8).astype(np.float32) / 255.0
        bb = np.frombuffer(seed_b, dtype=np.uint8).astype(np.float32) / 255.0

    # np.linalg.norm：计算向量的 L2 范数（即欧氏距离）
    return float(np.linalg.norm(aa - bb))


def match_student(embedding: list[float], students: list[dict]) -> FaceMatch | None:
    """
    在学生数据库中找到与给定人脸最相似的学生
    
    算法：暴力最近邻搜索（Brute-Force Nearest Neighbor）
    - 计算目标向量与所有学生向量的距离
    - 找最近的那个
    - 如果距离超过阈值，认为是陌生人，返回 None
    
    返回：FaceMatch（匹配到）或 None（没有匹配到）
    """
    from .config import HAS_FACE_RECOGNITION, FACE_MATCH_THRESHOLD_HIGH_QUALITY, FACE_MATCH_THRESHOLD_LIGHTWEIGHT

    if not students:   # 数据库为空，直接返回
        return None

    target_emb = np.array(embedding, dtype=np.float32)

    # 优化：如果所有学生向量维度相同，用矩阵运算批量计算距离（比循环快）
    same_dims = all(len(s["embedding"]) == len(embedding) for s in students)
    if same_dims:
        # db_embeddings：shape = (学生数, 维度)，例如 (50, 128)
        db_embeddings = np.array([s["embedding"] for s in students], dtype=np.float32)

        # target_emb 自动广播（broadcasting），逐行计算距离
        distances = np.linalg.norm(db_embeddings - target_emb, axis=1)
    else:
        # 维度不同，逐个计算（调用可处理不同长度的 embedding_distance）
        distances = np.array(
            [embedding_distance(embedding, student["embedding"]) for student in students],
            dtype=np.float32,
        )

    # 找最小距离的索引
    best_idx = int(np.argmin(distances))
    min_dist = float(distances[best_idx])

    # 根据使用的模型选择对应阈值
    threshold = FACE_MATCH_THRESHOLD_HIGH_QUALITY if HAS_FACE_RECOGNITION else FACE_MATCH_THRESHOLD_LIGHTWEIGHT

    # 距离超过阈值 → 认为是陌生人，不匹配
    if min_dist > threshold:
        return None

    return FaceMatch(
        student_id=students[best_idx]["student_id"],
        student_name=students[best_idx]["name"],
        score=min_dist,
    )


# ============================================================
# 活体检测（防止用照片/视频欺骗签到）
# ============================================================

def liveness_check(face_region: np.ndarray) -> tuple[bool, str]:
    """
    活体检测：判断摄像头前的是真人还是照片/屏幕
    
    使用三重检测策略（都是启发式方法，不用深度学习）：
    1. 模糊度检测：真人在摄像头前有自然的清晰度变化
    2. 频域纹理检测：打印照片/屏幕有异常高频纹理
    3. 饱和度检测：灰度照片缺乏颜色信息
    
    返回：(是否通过, 原因说明)
    """
    gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)

    # --- 检测1：模糊度 ---
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))

    # 照片/屏幕常出现过于平整或过于锐利的边缘，双向都可疑。
    blur_min_threshold = 38.0 if brightness > 50 else 24.0
    blur_max_threshold = 4500.0
    if blur_score < blur_min_threshold:
        return False, (
            "Image too blurry, please ensure good lighting "
            f"(blur={blur_score:.2f}, threshold={blur_min_threshold:.2f}, brightness={brightness:.2f})"
        )
    if blur_score > blur_max_threshold:
        return False, (
            "Suspiciously sharp face region detected "
            f"(blur={blur_score:.2f}, threshold={blur_max_threshold:.2f})"
        )

    # --- 检测2：纹理一致性 ---
    # 打印照片/屏幕通常会出现规则纹理，但真实人脸的局部纹理变化更自然。
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    texture_score = float(np.std(laplacian))
    texture_threshold = 22.0
    if texture_score < texture_threshold:
        return False, (
            "Low texture diversity detected "
            f"(texture={texture_score:.2f}, threshold={texture_threshold:.2f})"
        )

    # --- 检测3：频域高频能量 ---
    dft = np.fft.fft2(gray)
    dft_shift = np.fft.fftshift(dft)
    magnitude_spectrum = np.log(np.abs(dft_shift) + 1)
    rows, cols = gray.shape
    crow, ccol = rows // 2, cols // 2
    low_freq_radius = max(12, min(rows, cols) // 10)
    magnitude_spectrum[
        crow - low_freq_radius:crow + low_freq_radius,
        ccol - low_freq_radius:ccol + low_freq_radius,
    ] = 0
    high_freq_score = float(np.mean(magnitude_spectrum))
    fft_threshold = 4.8
    if high_freq_score > fft_threshold:
        return False, (
            "Suspicious texture detected (Anti-spoofing triggered) "
            f"(fft={high_freq_score:.2f}, threshold={fft_threshold:.2f})"
        )

    # --- 检测4：颜色饱和度 ---
    hsv = cv2.cvtColor(face_region, cv2.COLOR_BGR2HSV)
    saturation = float(np.mean(hsv[:, :, 1]))
    saturation_min_threshold = 14.0
    saturation_max_threshold = 235.0

    if saturation < saturation_min_threshold:
        return False, (
            "Abnormal color distribution "
            f"(saturation={saturation:.2f}, threshold={saturation_min_threshold:.2f})"
        )
    if saturation > saturation_max_threshold:
        return False, (
            "Abnormal color saturation detected "
            f"(saturation={saturation:.2f}, threshold={saturation_max_threshold:.2f})"
        )

    # 综合评分：把各项结果汇总，便于调试和后续调参。
    liveness_score = (
        min(1.0, blur_score / blur_min_threshold) * 0.35
        + min(1.0, texture_score / texture_threshold) * 0.25
        + max(0.0, 1.0 - abs(high_freq_score - 3.2) / 3.2) * 0.2
        + min(1.0, saturation / 80.0) * 0.2
    )
    if liveness_score < 0.72:
        return False, (
            "Liveness score too low "
            f"(score={liveness_score:.2f}, blur={blur_score:.2f}, texture={texture_score:.2f}, "
            f"fft={high_freq_score:.2f}, saturation={saturation:.2f})"
        )

    return True, (
        "Liveness passed "
        f"(score={liveness_score:.2f}, blur={blur_score:.2f}, texture={texture_score:.2f}, "
        f"fft={high_freq_score:.2f}, saturation={saturation:.2f})"
    )


# ============================================================
# 情绪分析
# ============================================================

def preprocess_face_for_emotion(face_region: np.ndarray) -> np.ndarray:
    """
    对人脸图片做预处理，提升情绪识别效果
    
    使用 CLAHE（限制对比度自适应直方图均衡化）：
    - 在图片的局部区域分别做直方图均衡化
    - 使过暗或过亮的区域变得更清晰，不过度放大噪声
    """
    # 转换到 LAB 颜色空间：L=亮度, A=绿-红, B=蓝-黄
    # 在 LAB 空间增强亮度通道（L），不影响颜色信息
    lab = cv2.cvtColor(face_region, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)

    # CLAHE：clipLimit 限制放大倍数（防止噪声过度放大），tileGridSize 是局部区域大小
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(l_channel)

    # 重新合并通道并转回 BGR
    merged = cv2.merge((enhanced_l, a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _refined_heuristic_emotion(face_region: np.ndarray) -> tuple[str, float, str]:
    """
    启发式情绪判断（不依赖深度学习，基于图像统计特征）
    
    原理：用简单的视觉指标近似情绪：
    - 图片整体偏暗 → 悲伤（阴郁）
    - 饱和度高且亮度高 → 开心（生动）
    - 边缘多且饱和度低 → 愤怒（紧张）
    - 亮度高且边缘丰富 → 惊讶（眼睛大开）
    - 其他 → 中性
    
    返回：(情绪标签, 置信度, "heuristic")
    """
    hsv = cv2.cvtColor(face_region, cv2.COLOR_BGR2HSV)
    saturation = float(np.mean(hsv[:, :, 1]))  # 平均饱和度
    value = float(np.mean(hsv[:, :, 2]))       # 平均亮度

    gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
    # Canny 边缘检测：找出图片中的轮廓/边缘像素
    # edge_density：边缘像素占所有像素的比例
    edge_density = float(np.mean(cv2.Canny(gray, 80, 160) > 0))

    if value < 70:
        return "sad", 52.0, "heuristic"
    if saturation > 95 and value > 135:
        return "happy", 55.0, "heuristic"
    if edge_density > 0.2 and saturation < 65:
        return "angry", 50.0, "heuristic"
    if value > 170 and edge_density > 0.17:
        return "surprised", 50.0, "heuristic"
    return "neutral", 48.0, "heuristic"


def analyze_emotion(face_region: np.ndarray) -> tuple[str, float, str]:
    """
    综合情绪分析：融合 DeepFace（深度学习）和启发式方法
    
    融合策略（加权投票）：
    - DeepFace 权重 70%（更准确，但偶尔失败或置信度低）
    - 启发式权重 30%（简单可靠，作为保底）
    
    情况一：DeepFace 置信度 < 40% → 用启发式结果
    情况二：两者预测相同 → 融合置信度
    情况三：两者不同 → 比较加权分数，高分者胜出
    
    返回：(情绪标签, 置信度0-100, 来源说明)
    """
    # 先做图像预处理
    processed_face = preprocess_face_for_emotion(face_region)

    # 启发式结果（总是可用的保底）
    h_emotion, h_confidence, _ = _refined_heuristic_emotion(processed_face)

    try:
        from deepface import DeepFace  # 尝试使用深度学习库

        result = DeepFace.analyze(
            processed_face,
            actions=["emotion"],         # 只分析情绪，不分析年龄性别
            detector_backend="opencv",   # 用 OpenCV 检测人脸（比默认的快）
            enforce_detection=False,     # 找不到脸也不报错（用整张图）
            align=True,                  # 人脸对齐（改善识别准确率）
            silent=True,                 # 不打印调试信息
        )

        # DeepFace 返回列表（可能多张脸），取第一个
        payload = result[0] if isinstance(result, list) else result

        if payload:
            # emotion_dict：{"happy": 85.3, "neutral": 10.2, "sad": 4.5, ...}
            emotion_dict = payload.get("emotion", {})

            if emotion_dict:
                # 找置信度最高的情绪
                dominant_emotion = max(emotion_dict, key=emotion_dict.get)
                confidence = float(emotion_dict.get(dominant_emotion, 0.0))

                # DeepFace 的标签 → 系统统一标签的映射
                # fear、disgust 映射为 unknown（不在我们的分类里）
                emotion_map = {
                    "happy": "happy", "sad": "sad", "angry": "angry",
                    "surprise": "surprised", "neutral": "neutral",
                    "fear": "unknown", "disgust": "unknown",
                }
                mapped = emotion_map.get(dominant_emotion, "unknown")

                # DeepFace 置信度太低，不可信，用启发式结果
                if confidence < 40.0:
                    return h_emotion, h_confidence, "heuristic_fallback_low_deepface_confidence"

                # 加权融合
                deepface_weight = 0.7
                heuristic_weight = 0.3

                if mapped == h_emotion:
                    # 两者一致：置信度直接融合
                    fused_confidence = confidence * deepface_weight + h_confidence * heuristic_weight
                    return mapped, float(fused_confidence), "fused_same_label"

                # 两者不一致：比较加权后的分数
                deepface_score = confidence * deepface_weight
                heuristic_score = h_confidence * heuristic_weight

                if deepface_score >= heuristic_score:
                    return mapped, float(deepface_score), "fused_deepface_dominant"
                return h_emotion, float(heuristic_score), "fused_heuristic_dominant"

    except Exception:
        pass  # DeepFace 报错（未安装或其他问题），静默降级

    # 最终兜底：返回启发式结果
    return h_emotion, h_confidence, "heuristic"
