# 班级考勤内容安全实验系统

本项目基于 BS 架构实现班级考勤实验系统，覆盖以下能力：

- 人脸注册与考勤打卡（活体检测 + 人脸比对）
- 班级/活动合照批量识别
- 考勤与识别过程中的情绪分类统计
- 异常处理（摄像头失败、上传失败、识别超时）

## 1. 项目结构

```
data9/
  backend/
    app/
      main.py
      services.py
      face_engine.py
      database.py
      models.py
      config.py
    tests/
      test_api.py
    requirements.txt
  frontend/
    index.html
    app.js
    styles.css
  docs/
    experiment-report.md
  data/
    attendance.db (运行后生成)
```

## 2. 快速启动

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

使用任意静态服务启动 frontend 目录，例如：

```bash
cd frontend
python -m http.server 5500
```

浏览器访问：

- 前端页面：http://127.0.0.1:5500
- 后端 API：http://127.0.0.1:8000/docs

## 3. 核心接口

- `POST /api/students/register`：学生注册
- `POST /api/attendance/check`：考勤打卡
- `POST /api/group-photo/recognize`：合照识别
- `GET /api/reports/activity`：活动参与频次统计
- `GET /api/reports/emotion`：情绪统计

## 4. 测试

```bash
cd backend
pytest -q
```

## 5. 内容安全边界与防护要点

- 活体检测为基础防护，应避免将单一阈值作为生产级判定依据。
- 情绪分析结果仅用于教学统计，不应用于个体惩戒、敏感决策。
- 面部数据需要最小化存储并严格授权访问，建议生产环境加密保存。
- 建议为接口增加鉴权、访问频控、审计日志与脱敏策略。

## 6. 说明

- 若环境中可安装 `face_recognition`，系统会优先使用其编码结果提升识别效果。
- 若未安装，系统自动回退到轻量 embedding 方案，便于实验演示与课程提交。
