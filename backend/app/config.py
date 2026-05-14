from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
FACE_DB_DIR = DATA_DIR / "face_data"
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
SQLITE_PATH = DATA_DIR / "attendance.db"

MAX_IMAGE_SIZE_MB = 8
# 人脸匹配阈值（距离越小越相似，阈值越大越宽松）
# 原值都是 0.65，现调整为：优先保证识别出来，容错能力更强
FACE_MATCH_THRESHOLD_HIGH_QUALITY = 0.85  # 高精度库：0.65 → 0.85
FACE_MATCH_THRESHOLD_LIGHTWEIGHT = 0.90   # 轻量级方案：0.65 → 0.90（更容易匹配）
API_TIMEOUT_SECONDS = 6
HAS_FACE_RECOGNITION = False

try:
    import face_recognition as _fr
    HAS_FACE_RECOGNITION = True
except Exception:
    pass
