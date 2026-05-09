from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import (
    get_activity_report,
    get_activity_detail,
    get_class_detail,
    get_daily_emotion_trend,
    get_emotion_report,
    get_student_activity_stats,
    init_db,
)
from .models import AttendanceRequest, RegisterStudentRequest
from .services import (
    check_attendance,
    export_attendance_to_excel,
    recognize_group_photo,
    register_student,
    register_student_with_photo,
)

app = FastAPI(title="Class Attendance Secure CV System", version="1.0.0")


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"message": str(exc)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"message": f"Internal server error: {str(exc)}"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    from .config import DATA_DIR, FACE_DB_DIR, UPLOAD_DIR, REPORT_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FACE_DB_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()


def verify_teacher_permission(x_role: str | None = Header(default=None)) -> None:
    if x_role != "teacher":
        raise HTTPException(status_code=403, detail="Permission denied: Teachers only")


@app.exception_handler(TimeoutError)
async def timeout_handler(request: Request, exc: TimeoutError):  # noqa: ARG001
    return JSONResponse(
        status_code=408,
        content={"message": "System is busy, face recognition timed out. Please try again."},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):  # noqa: ARG001
    return JSONResponse(
        status_code=400,
        content={"message": str(exc)},
    )


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/students/register")
def api_register_student(payload: RegisterStudentRequest, x_role: str | None = Header(default=None)) -> dict:
    verify_teacher_permission(x_role)
    return register_student(payload.student_id, payload.name, payload.image_base64)


@app.post("/api/attendance/check")
def api_attendance(payload: AttendanceRequest):
    return check_attendance(payload.classroom_id, payload.teacher_name, payload.image_base64)


@app.post("/api/group-photo/recognize")
async def api_group_photo_recognize(
    activity_name: str = Form(...),
    activity_type: str = Form(default="other"),
    activity_time: str = Form(default=None),
    file: UploadFile = File(...),
):
    if not activity_name.strip():
        raise HTTPException(status_code=400, detail="必须填写活动名称才能开始签到")
    
    raw = await file.read()
    return recognize_group_photo(activity_name, raw, activity_type, activity_time)


@app.get("/api/reports/activity")
def api_activity_report(x_role: str | None = Header(default=None)) -> dict:
    verify_teacher_permission(x_role)
    return {"items": get_activity_report()}


@app.get("/api/reports/emotion")
def api_emotion_report(x_role: str | None = Header(default=None)) -> dict:
    verify_teacher_permission(x_role)
    return {"items": get_emotion_report()}


@app.get("/api/reports/activity-stats")
def api_student_activity_stats(x_role: str | None = Header(default=None)) -> dict:
    verify_teacher_permission(x_role)
    return {"items": get_student_activity_stats()}


@app.get("/api/reports/emotion-trend")
def api_daily_emotion_trend(x_role: str | None = Header(default=None)) -> dict:
    verify_teacher_permission(x_role)
    return {"items": get_daily_emotion_trend()}


@app.post("/api/reports/export-attendance")
def api_export_attendance(x_role: str | None = Header(default=None)) -> dict:
    verify_teacher_permission(x_role)
    return {"file_path": export_attendance_to_excel()}


@app.post("/api/register")
async def api_register_student_with_photo(
    student_id: str = Form(...),
    student_name: str = Form(...),
    major: str = Form(...),
    gender: str = Form(...),
    file: UploadFile = File(...),
):
    raw = await file.read()
    return register_student_with_photo(student_id, student_name, major, gender, raw)


@app.get("/api/reports/class-detail")
def api_class_detail(classroom_id: str, x_role: str | None = Header(default=None)) -> dict:
    verify_teacher_permission(x_role)
    return get_class_detail(classroom_id)


@app.get("/api/reports/activity-detail")
def api_activity_detail(activity_name: str, x_role: str | None = Header(default=None)) -> dict:
    verify_teacher_permission(x_role)
    return get_activity_detail(activity_name)
