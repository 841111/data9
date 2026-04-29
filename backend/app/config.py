from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
FACE_DB_DIR = DATA_DIR / "face_db"
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
SQLITE_PATH = DATA_DIR / "attendance.db"

MAX_IMAGE_SIZE_MB = 8
FACE_MATCH_THRESHOLD_HIGH_QUALITY = 0.65
FACE_MATCH_THRESHOLD_LIGHTWEIGHT = 0.65
API_TIMEOUT_SECONDS = 6
HAS_FACE_RECOGNITION = False

try:
    import face_recognition as _fr
    HAS_FACE_RECOGNITION = True
except Exception:
    pass
