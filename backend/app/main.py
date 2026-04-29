from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import (
    get_activity_report,
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
)

app = FastAPI(title="Class Attendance Secure CV System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
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
    return check_attendance(payload.classroom_id, payload.image_base64)


@app.post("/api/group-photo/recognize")
async def api_group_photo_recognize(
    activity_name: str = Form(default="default_activity"), file: UploadFile = File(...)
):
    raw = await file.read()
    return recognize_group_photo(activity_name, raw)


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
