# 从 FastAPI 框架中导入常用组件
# FastAPI: 创建 Web API 应用
# File/Form: 接收上传文件和表单数据
# Header: 获取请求头信息
# HTTPException: 抛出 HTTP 异常
# Request: 请求对象
# UploadFile: 上传文件对象
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile

# 导入 CORS 中间件（跨域资源共享）
# 用于允许前端页面访问后端接口
from fastapi.middleware.cors import CORSMiddleware

# 导入 JSONResponse，用于返回 JSON 格式响应
from fastapi.responses import JSONResponse

# 从 database 模块导入数据库相关函数
from .database import (

    # 获取活动签到统计报告
    get_activity_report,

    # 获取某个活动的详细信息
    get_activity_detail,

    # 获取某个班级的详细信息
    get_class_detail,

    # 获取每日情绪趋势统计
    get_daily_emotion_trend,

    # 获取情绪分析报告
    get_emotion_report,

    # 获取学生活动统计
    get_student_activity_stats,

    # 初始化数据库
    init_db,
)

# 导入数据模型（请求参数模型）
from .models import (

    # 考勤请求的数据结构
    AttendanceRequest,

    # 学生注册请求的数据结构
    RegisterStudentRequest
)

# 从 services 模块导入业务逻辑函数
from .services import (

    # 检查签到
    check_attendance,

    # 导出签到记录到 Excel
    export_attendance_to_excel,

    # 识别集体照片中的学生
    recognize_group_photo,

    # 注册学生（base64图片方式）
    register_student,

    # 注册学生（上传图片方式）
    register_student_with_photo,
)

# 创建 FastAPI 应用对象
# title: API 名称
# version: 版本号
app = FastAPI(title="Class Attendance Secure CV System", version="1.0.0")


# =========================
# 异常处理部分
# =========================


# 注册 ValueError 异常处理器
# 当代码抛出 ValueError 时会自动调用该函数
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    # 返回 HTTP 400 错误（客户端请求错误）
    return JSONResponse(
        status_code=400,

        # 返回错误信息
        content={"message": str(exc)},
    )


# 注册通用异常处理器
# 捕获所有未处理的异常
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    # 返回 HTTP 500 错误（服务器内部错误）
    return JSONResponse(
        status_code=500,

        # 返回异常信息
        content={"message": f"Internal server error: {str(exc)}"},
    )


# =========================
# 配置 CORS 跨域
# =========================


app.add_middleware(

    # 添加 CORS 中间件
    CORSMiddleware,

    # 允许访问的前端地址
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000"
    ],

    # 允许发送 Cookie
    allow_credentials=True,

    # 允许所有 HTTP 方法（GET/POST 等）
    allow_methods=["*"],

    # 允许所有请求头
    allow_headers=["*"],
)


# =========================
# 启动时执行
# =========================


# 应用启动时自动执行 startup() 函数
@app.on_event("startup")
def startup() -> None:
    # 导入配置中的目录路径
    from .config import DATA_DIR, FACE_DB_DIR, UPLOAD_DIR, REPORT_DIR

    # 创建数据目录（如果不存在）
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 创建人脸数据库目录
    FACE_DB_DIR.mkdir(parents=True, exist_ok=True)

    # 创建上传目录
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 创建报告目录
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # 初始化数据库
    init_db()


# =========================
# 权限校验函数
# =========================


# 验证教师权限
# 从请求头中读取 x_role
def verify_teacher_permission(x_role: str | None = Header(default=None)) -> None:
    # 如果角色不是 teacher
    if x_role != "teacher":
        # 抛出 403 禁止访问异常
        raise HTTPException(status_code=403, detail="Permission denied: Teachers only")


# =========================
# 超时异常处理
# =========================


# 注册 TimeoutError 异常处理器
@app.exception_handler(TimeoutError)
async def timeout_handler(request: Request, exc: TimeoutError):  # noqa: ARG001

    # 返回 HTTP 408 请求超时
    return JSONResponse(
        status_code=408,

        # 返回提示信息
        content={"message": "System is busy, face recognition timed out. Please try again."},
    )


# =========================
# 健康检查接口
# =========================


# GET 请求接口
@app.get("/api/health")
def health() -> dict:
    # 返回服务器状态
    return {"ok": True}


# =========================
# 学生注册接口（Base64 图片）
# =========================


@app.post("/api/students/register")
def api_register_student(

        # 请求体参数
        payload: RegisterStudentRequest,

        # 从请求头获取角色
        x_role: str | None = Header(default=None)

) -> dict:
    # 验证教师权限
    verify_teacher_permission(x_role)

    # 调用注册函数
    return register_student(
        payload.student_id,
        payload.name,
        payload.image_base64
    )


# =========================
# 考勤签到接口
# =========================


@app.post("/api/attendance/check")
def api_attendance(payload: AttendanceRequest):
    # 调用签到检查函数
    return check_attendance(
        payload.classroom_id,
        payload.teacher_name,
        payload.image_base64
    )


# =========================
# 集体照片识别接口
# =========================


@app.post("/api/group-photo/recognize")
async def api_group_photo_recognize(

        # 活动名称（表单参数）
        activity_name: str = Form(...),

        # 活动类型，默认 other
        activity_type: str = Form(default="other"),

        # 活动时间
        activity_time: str = Form(default=None),

        # 上传的文件
        file: UploadFile = File(...),
):
    # 检查活动名称是否为空
    if not activity_name.strip():
        # 如果为空，返回 400 错误
        raise HTTPException(status_code=400, detail="必须填写活动名称才能开始签到")

    # 读取上传文件的二进制内容
    raw = await file.read()

    # 调用集体照片识别函数
    return recognize_group_photo(
        activity_name,
        raw,
        activity_type,
        activity_time
    )


# =========================
# 活动统计报告接口
# =========================


@app.get("/api/reports/activity")
def api_activity_report(x_role: str | None = Header(default=None)) -> dict:
    # 验证教师权限
    verify_teacher_permission(x_role)

    # 返回活动报告
    return {"items": get_activity_report()}


# =========================
# 情绪分析报告接口
# =========================


@app.get("/api/reports/emotion")
def api_emotion_report(x_role: str | None = Header(default=None)) -> dict:
    # 验证权限
    verify_teacher_permission(x_role)

    # 返回情绪报告
    return {"items": get_emotion_report()}


# =========================
# 学生活动统计接口
# =========================


@app.get("/api/reports/activity-stats")
def api_student_activity_stats(x_role: str | None = Header(default=None)) -> dict:
    # 验证权限
    verify_teacher_permission(x_role)

    # 返回统计数据
    return {"items": get_student_activity_stats()}


# =========================
# 每日情绪趋势接口
# =========================


@app.get("/api/reports/emotion-trend")
def api_daily_emotion_trend(x_role: str | None = Header(default=None)) -> dict:
    # 验证权限
    verify_teacher_permission(x_role)

    # 返回趋势数据
    return {"items": get_daily_emotion_trend()}


# =========================
# 导出签到 Excel 接口
# =========================


@app.post("/api/reports/export-attendance")
def api_export_attendance(x_role: str | None = Header(default=None)) -> dict:
    # 验证权限
    verify_teacher_permission(x_role)

    # 导出 Excel 并返回文件路径
    return {"file_path": export_attendance_to_excel()}


# =========================
# 上传照片注册学生接口
# =========================


@app.post("/api/register")
async def api_register_student_with_photo(

        # 学号
        student_id: str = Form(...),

        # 学生姓名
        student_name: str = Form(...),

        # 专业
        major: str = Form(...),

        # 性别
        gender: str = Form(...),

        # 上传照片
        file: UploadFile = File(...),
):
    # 读取上传图片数据
    raw = await file.read()

    # 调用注册函数
    return register_student_with_photo(
        student_id,
        student_name,
        major,
        gender,
        raw
    )


# =========================
# 班级详情接口
# =========================


@app.get("/api/reports/class-detail")
def api_class_detail(

        # 班级 ID
        classroom_id: str,

        # 请求头中的角色
        x_role: str | None = Header(default=None)

) -> dict:
    # 验证权限
    verify_teacher_permission(x_role)

    # 返回班级详情
    return get_class_detail(classroom_id)


# =========================
# 活动详情接口
# =========================


@app.get("/api/reports/activity-detail")
def api_activity_detail(

        # 活动名称
        activity_name: str,

        # 请求头角色
        x_role: str | None = Header(default=None)

) -> dict:
    # 验证权限
    verify_teacher_permission(x_role)

    # 返回活动详情
    return get_activity_detail(activity_name)