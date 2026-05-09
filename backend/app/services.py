import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from pathlib import Path

import cv2

from .config import API_TIMEOUT_SECONDS, REPORT_DIR, FACE_DB_DIR
from .database import (
    _get_connection,
    fetch_students,
    fetch_students_from_face_data,
    insert_activity,
    insert_activity_with_details,
    insert_attendance,
    upsert_student,
    upsert_student_with_details,
)
from .face_engine import (
    analyze_emotion,
    crop_face_with_margin,
    decode_base64_image,
    decode_upload_image,
    detect_faces,
    face_embedding,
    liveness_check,
    match_student,
    preprocess_face_for_emotion,
)
from .models import AttendanceResult, GroupRecognitionItem, GroupRecognitionResponse

last_processed_hash: dict[str, tuple[str, float, float]] = {}
REPLAY_WINDOW_SECONDS = 1.0
_timeout_executor = ThreadPoolExecutor(max_workers=4)


def with_timeout(func, *args, **kwargs):
    future = _timeout_executor.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=API_TIMEOUT_SECONDS)
    except FuturesTimeoutError as exc:
        raise TimeoutError("Recognition timeout") from exc


def _process_single_face(face_data: tuple) -> GroupRecognitionItem | None:
    image, coords, students, activity_name, activity_type, activity_time = face_data
    x, y, w, h = coords
    try:
        face_region = crop_face_with_margin(image, x, y, w, h)
        emb = with_timeout(face_embedding, face_region)
        matched = with_timeout(match_student, emb, students)
        if matched is None:
            return None

        emotion, emotion_confidence, emotion_source = analyze_emotion(face_region)
        insert_activity_with_details(activity_name, activity_type, activity_time, matched.student_id, matched.student_name)
        return GroupRecognitionItem(
            student_id=matched.student_id,
            student_name=matched.student_name,
            score=matched.score,
            emotion=emotion,
            emotion_confidence=emotion_confidence,
            emotion_source=emotion_source,
        )
    except Exception:
        return None


def register_student(student_id: str, name: str, image_base64: str) -> dict:
    image = decode_base64_image(image_base64)
    faces = detect_faces(image)
    if len(faces) != 1:
        raise ValueError("Registration image must contain exactly one face")

    x, y, w, h = faces[0]
    face = crop_face_with_margin(image, x, y, w, h)
    embedding = face_embedding(face)
    upsert_student(student_id=student_id, name=name, embedding=embedding)

    return {"success": True, "student_id": student_id, "name": name}


def check_attendance(classroom_id: str, teacher_name: str, image_base64: str) -> AttendanceResult:
    try:
        if not image_base64 or len(image_base64) < 100:
            raise ValueError("Camera data is corrupted or empty")

        now_ts = time.time()
        img_hash = hashlib.md5(image_base64.encode("utf-8")).hexdigest()
        previous = last_processed_hash.get(classroom_id)
        if previous is not None:
            previous_hash, previous_ts, previous_blur_score = previous
            if now_ts - previous_ts <= REPLAY_WINDOW_SECONDS and previous_hash == img_hash:
                time_value = insert_attendance(
                    classroom_id=classroom_id,
                    teacher_name=teacher_name,
                    success=False,
                    reason="Duplicate frame detected",
                    liveness_passed=False,
                    emotion="unknown",
                )
                return AttendanceResult(
                    success=False,
                    reason="Duplicate frame detected",
                    liveness_passed=False,
                    emotion="unknown",
                    attendance_time=time_value,
                )

        image = decode_base64_image(image_base64)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if previous is not None:
            previous_hash, previous_ts, previous_blur_score = previous
            if (
                now_ts - previous_ts <= REPLAY_WINDOW_SECONDS
                and abs(blur_score - previous_blur_score) < 1e-6
            ):
                time_value = insert_attendance(
                    classroom_id=classroom_id,
                    teacher_name=teacher_name,
                    success=False,
                    reason="Suspicious replay pattern detected",
                    liveness_passed=False,
                    emotion="unknown",
                )
                return AttendanceResult(
                    success=False,
                    reason="Suspicious replay pattern detected",
                    liveness_passed=False,
                    emotion="unknown",
                    attendance_time=time_value,
                )

        last_processed_hash[classroom_id] = (img_hash, now_ts, blur_score)
        faces = detect_faces(image)

        if len(faces) == 0:
            time_value = insert_attendance(
                classroom_id=classroom_id,
                teacher_name=teacher_name,
                success=False,
                reason="No face detected",
                liveness_passed=False,
                emotion="unknown",
            )
            return AttendanceResult(
                success=False,
                reason="No face detected",
                liveness_passed=False,
                emotion="unknown",
                attendance_time=time_value,
            )

        x, y, w, h = faces[0]
        face = crop_face_with_margin(image, x, y, w, h)
        face = preprocess_face_for_emotion(face)
        emb = with_timeout(face_embedding, face)
        
        students = fetch_students_from_face_data()
        if not students:
            students = fetch_students()

        from .face_engine import embedding_distance

        debug_scores = [(s["student_id"], float(embedding_distance(emb, s["embedding"]))) for s in students]

        matched = with_timeout(match_student, emb, students)
        liveness_passed, liveness_message = liveness_check(face)
        emotion, emotion_confidence, emotion_source = analyze_emotion(face)

        if matched is None:
            reason = "No matched student - Please register first"
            if not liveness_passed:
                reason = f"{reason}; Risk: {liveness_message}"
            time_value = insert_attendance(
                classroom_id=classroom_id,
                teacher_name=teacher_name,
                success=False,
                reason=reason,
                liveness_passed=liveness_passed,
                emotion=emotion,
            )
            return AttendanceResult(
                success=False,
                reason=reason,
                liveness_passed=liveness_passed,
                emotion=emotion,
                emotion_confidence=emotion_confidence,
                emotion_source=emotion_source,
                debug_scores=debug_scores,
                attendance_time=time_value,
            )

        reason = "Attendance success" if liveness_passed else f"Success with Risk: {liveness_message}"
        time_value = insert_attendance(
            classroom_id=classroom_id,
            teacher_name=teacher_name,
            success=True,
            reason=reason,
            student_id=matched.student_id,
            student_name=matched.student_name,
            score=matched.score,
            liveness_passed=liveness_passed,
            emotion=emotion,
        )
        return AttendanceResult(
            success=True,
            reason=reason,
            student_id=matched.student_id,
            student_name=matched.student_name,
            score=matched.score,
            liveness_passed=liveness_passed,
            emotion=emotion,
            emotion_confidence=emotion_confidence,
            emotion_source=emotion_source,
            debug_scores=debug_scores,
            attendance_time=time_value,
        )
    except ValueError as exc:
        return AttendanceResult(
            success=False,
            reason=f"Device Error: {str(exc)}",
            liveness_passed=False,
            emotion="unknown",
        )
    except TimeoutError:
        return AttendanceResult(
            success=False,
            reason="System busy, please try again",
            liveness_passed=False,
            emotion="unknown",
        )


def recognize_group_photo(
    activity_name: str,
    raw: bytes,
    activity_type: str = "other",
    activity_time: str | None = None,
) -> GroupRecognitionResponse:
    image = decode_upload_image(raw)
    faces = detect_faces(image)
    
    students = fetch_students_from_face_data()
    if not students:
        students = fetch_students()

    if not faces:
        return GroupRecognitionResponse(
            success=True,
            total_faces=0,
            matched_count=0,
            matched_students=[],
        )

    task_data = [(image, face_coords, students, activity_name, activity_type, activity_time) for face_coords in faces]
    worker_target = (os.cpu_count() or 1) * 2
    max_workers = max(1, min(len(faces), worker_target, 8))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_process_single_face, task_data))

    matched_items = [item for item in results if item is not None]

    return GroupRecognitionResponse(
        success=True,
        total_faces=len(faces),
        matched_count=len(matched_items),
        matched_students=matched_items,
    )


def export_attendance_to_excel() -> str:
    try:
        import pandas as pd
    except Exception as exc:
        raise ValueError("Excel export requires pandas and openpyxl") from exc

    conn = _get_connection()
    df = pd.read_sql_query("SELECT * FROM attendance", conn)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = REPORT_DIR / f"attendance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(file_path, index=False)
    return str(file_path)


def register_student_with_photo(
    student_id: str,
    student_name: str,
    major: str,
    gender: str,
    image_data: bytes,
) -> dict:
    image = decode_upload_image(image_data)
    faces = detect_faces(image)
    
    if len(faces) == 0:
        raise ValueError("未检测到人脸，请确保照片中只有一个人脸且光线充足")
    elif len(faces) > 1:
        raise ValueError("检测到多个人脸，请确保照片中只有一个人脸")
    
    x, y, w, h = faces[0]
    face = crop_face_with_margin(image, x, y, w, h)
    embedding = face_embedding(face)
    
    upsert_student_with_details(student_id, student_name, major, gender, embedding)
    
    FACE_DB_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{student_id}-{student_name}-{major}-{gender}.jpg"
    file_path = FACE_DB_DIR / filename
    cv2.imwrite(str(file_path), cv2.cvtColor(face, cv2.COLOR_RGB2BGR))
    
    return {
        "success": True,
        "student_id": student_id,
        "student_name": student_name,
        "file_path": str(file_path),
    }
