import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from .config import SQLITE_PATH

_global_conn: sqlite3.Connection | None = None
_student_cache: list[dict] | None = None
_cache_timestamp: float = 0.0
CACHE_TTL_SECONDS = 300.0


def _get_connection() -> sqlite3.Connection:
    global _global_conn
    if _global_conn is None:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _global_conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        _global_conn.row_factory = sqlite3.Row
    return _global_conn


def init_db() -> None:
    conn = _get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            major TEXT,
            gender TEXT,
            embedding TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            classroom_id TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            student_id TEXT,
            student_name TEXT,
            success INTEGER NOT NULL,
            reason TEXT NOT NULL,
            score REAL,
            liveness_passed INTEGER NOT NULL,
            emotion TEXT NOT NULL,
            attendance_time TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_name TEXT NOT NULL,
            activity_type TEXT,
            activity_time TEXT,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            recognized_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def upsert_student(student_id: str, name: str, embedding: list[float]) -> None:
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO students(student_id, name, embedding, created_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(student_id)
        DO UPDATE SET name=excluded.name, embedding=excluded.embedding
        """,
        (student_id, name, json.dumps(embedding), datetime.utcnow().isoformat()),
    )
    conn.commit()
    invalidate_student_cache()


def upsert_student_with_details(
    student_id: str, 
    name: str, 
    major: str, 
    gender: str, 
    embedding: list[float]
) -> None:
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO students(student_id, name, major, gender, embedding, created_at)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id)
        DO UPDATE SET name=excluded.name, major=excluded.major, gender=excluded.gender, embedding=excluded.embedding
        """,
        (student_id, name, major, gender, json.dumps(embedding), datetime.utcnow().isoformat()),
    )
    conn.commit()
    invalidate_student_cache()


def fetch_students() -> list[dict]:
    global _student_cache, _cache_timestamp
    
    current_time = time.time()
    
    if _student_cache is not None and (current_time - _cache_timestamp) < CACHE_TTL_SECONDS:
        return _student_cache
    
    students = []
    
    conn = _get_connection()
    rows = conn.execute("SELECT * FROM students").fetchall()
    
    for row in rows:
        student_data = {
            "student_id": row["student_id"],
            "name": row["name"],
            "embedding": json.loads(row["embedding"]),
        }
        students.append(student_data)
    
    _student_cache = students
    _cache_timestamp = current_time
    
    return _student_cache


def fetch_students_from_face_data() -> list[dict]:
    from .config import FACE_DB_DIR
    from .face_engine import face_embedding, decode_upload_image
    import cv2
    
    students = []
    
    if not FACE_DB_DIR.exists():
        return students
    
    for image_file in FACE_DB_DIR.glob("*.jpg"):
        try:
            filename = image_file.stem
            parts = filename.split("-")
            
            if len(parts) >= 2:
                student_id = parts[0]
                student_name = parts[1]
                
                image = cv2.imread(str(image_file))
                if image is not None:
                    embedding = face_embedding(image)
                    students.append({
                        "student_id": student_id,
                        "name": student_name,
                        "embedding": embedding,
                    })
        except Exception:
            continue
    
    return students


def invalidate_student_cache() -> None:
    global _student_cache, _cache_timestamp
    _student_cache = None
    _cache_timestamp = 0.0


def insert_attendance(
    classroom_id: str,
    teacher_name: str,
    success: bool,
    reason: str,
    liveness_passed: bool,
    emotion: str,
    student_id: str | None = None,
    student_name: str | None = None,
    score: float | None = None,
) -> str:
    attendance_time = datetime.utcnow().isoformat()
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO attendance(
            classroom_id, teacher_name, student_id, student_name, success, reason,
            score, liveness_passed, emotion, attendance_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            classroom_id,
            teacher_name,
            student_id,
            student_name,
            1 if success else 0,
            reason,
            score,
            1 if liveness_passed else 0,
            emotion,
            attendance_time,
        ),
    )
    conn.commit()
    return attendance_time


def insert_activity(activity_name: str, student_id: str, student_name: str) -> None:
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO activity_stats(activity_name, student_id, student_name, recognized_at)
        VALUES (?, ?, ?, ?)
        """,
        (activity_name, student_id, student_name, datetime.utcnow().isoformat()),
    )
    conn.commit()


def insert_activity_with_details(
    activity_name: str,
    activity_type: str,
    activity_time: str | None,
    student_id: str,
    student_name: str,
) -> None:
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO activity_stats(activity_name, activity_type, activity_time, student_id, student_name, recognized_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (activity_name, activity_type, activity_time, student_id, student_name, datetime.utcnow().isoformat()),
    )
    conn.commit()


def get_class_detail(classroom_id: str) -> dict:
    conn = _get_connection()
    
    list_rows = conn.execute(
        """
        SELECT student_id, student_name, COUNT(*) AS attendance_count
        FROM attendance
        WHERE classroom_id = ? AND success = 1
        GROUP BY student_id, student_name
        ORDER BY attendance_count DESC
        """,
        (classroom_id,),
    ).fetchall()
    
    emotion_rows = conn.execute(
        """
        SELECT emotion, COUNT(*) AS count
        FROM attendance
        WHERE classroom_id = ? AND success = 1
        GROUP BY emotion
        ORDER BY count DESC
        """,
        (classroom_id,),
    ).fetchall()
    
    return {
        "list": [dict(row) for row in list_rows],
        "emotions": [dict(row) for row in emotion_rows],
    }


def get_activity_detail(activity_name: str) -> dict:
    conn = _get_connection()
    
    list_rows = conn.execute(
        """
        SELECT student_id, student_name, COUNT(*) AS activity_count
        FROM activity_stats
        WHERE activity_name = ?
        GROUP BY student_id, student_name
        ORDER BY activity_count DESC
        """,
        (activity_name,),
    ).fetchall()
    
    emotion_rows = conn.execute(
        """
        SELECT emotion, COUNT(*) AS count
        FROM attendance
        WHERE student_id IN (
            SELECT DISTINCT student_id FROM activity_stats WHERE activity_name = ?
        )
        GROUP BY emotion
        ORDER BY count DESC
        """,
        (activity_name,),
    ).fetchall()
    
    return {
        "list": [dict(row) for row in list_rows],
        "emotions": [dict(row) for row in emotion_rows],
    }


def get_activity_report() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        """
        SELECT student_id, student_name, COUNT(*) AS frequency
        FROM activity_stats
        GROUP BY student_id, student_name
        ORDER BY frequency DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_emotion_report() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        """
        SELECT emotion, COUNT(*) AS count
        FROM attendance
        GROUP BY emotion
        ORDER BY count DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_student_activity_stats() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        """
        SELECT student_id, student_name, COUNT(*) AS activity_count
        FROM activity_stats
        GROUP BY student_id, student_name
        ORDER BY activity_count DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_daily_emotion_trend() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        """
        SELECT date(attendance_time) AS day, emotion, COUNT(*) AS count
        FROM attendance
        WHERE success = 1
        GROUP BY day, emotion
        ORDER BY day ASC, count DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]
