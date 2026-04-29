import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import SQLITE_PATH

_global_conn: sqlite3.Connection | None = None


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


def fetch_students() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute("SELECT * FROM students").fetchall()
    return [
        {
            "student_id": row["student_id"],
            "name": row["name"],
            "embedding": json.loads(row["embedding"]),
        }
        for row in rows
    ]


def insert_attendance(
    classroom_id: str,
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
            classroom_id, student_id, student_name, success, reason,
            score, liveness_passed, emotion, attendance_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            classroom_id,
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
