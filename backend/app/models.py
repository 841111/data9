from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RegisterStudentRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=32)
    image_base64: str


class AttendanceRequest(BaseModel):
    classroom_id: str = Field(..., min_length=1, max_length=64, description="课程名称")
    teacher_name: str = Field(..., min_length=1, max_length=64, description="教师姓名")
    image_base64: str


class AttendanceResult(BaseModel):
    success: bool
    reason: str
    student_id: str | None = None
    student_name: str | None = None
    score: float | None = None
    liveness_passed: bool = False
    emotion: Literal[
        "happy", "neutral", "sad", "angry", "surprised", "unknown"
    ] = "unknown"
    emotion_confidence: float | None = None
    emotion_source: str | None = None
    debug_scores: list[tuple[str, float]] | None = None
    attendance_time: datetime = Field(default_factory=datetime.utcnow)


class GroupRecognitionItem(BaseModel):
    student_id: str
    student_name: str
    score: float
    emotion: str
    emotion_confidence: float | None = None
    emotion_source: str | None = None


class GroupRecognitionResponse(BaseModel):
    success: bool
    total_faces: int
    matched_count: int
    matched_students: list[GroupRecognitionItem]


class RegisterStudentPhotoRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=32)
    student_name: str = Field(min_length=1, max_length=32)
    major: str = Field(min_length=1, max_length=64)
    gender: str = Field(min_length=1, max_length=8)


class ExcelImportResponse(BaseModel):
    success_count: int
    failed_count: int
    failed_list: list[str] = []
