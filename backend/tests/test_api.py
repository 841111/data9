import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _blank_image_base64() -> str:
    img = Image.new("RGB", (320, 240), color=(180, 180, 180))
    buff = io.BytesIO()
    img.save(buff, format="JPEG")
    return base64.b64encode(buff.getvalue()).decode("utf-8")


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_attendance_no_face(client):
    payload = {"classroom_id": "class-1", "image_base64": _blank_image_base64()}
    resp = client.post("/api/attendance/check", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "No face" in body["reason"]
