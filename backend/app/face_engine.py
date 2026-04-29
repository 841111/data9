import base64
import hashlib
import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .config import MAX_IMAGE_SIZE_MB

try:
    import face_recognition  # type: ignore
except Exception:
    face_recognition = None


@dataclass
class FaceMatch:
    student_id: str
    student_name: str
    score: float


def decode_base64_image(image_base64: str) -> np.ndarray:
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]
    raw = base64.b64decode(image_base64, validate=True)
    if len(raw) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise ValueError("Image too large")
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def decode_upload_image(raw: bytes) -> np.ndarray:
    if len(raw) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise ValueError("Image too large")
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def detect_faces(image: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]


def crop_face_with_margin(
    image: np.ndarray, x: int, y: int, w: int, h: int, margin_ratio: float = 0.22
) -> np.ndarray:
    ih, iw = image.shape[:2]
    dx = int(w * margin_ratio)
    dy = int(h * margin_ratio)
    x1 = max(0, x - dx)
    y1 = max(0, y - dy)
    x2 = min(iw, x + w + dx)
    y2 = min(ih, y + h + dy)
    return image[y1:y2, x1:x2]


def _fallback_embedding(face_region: np.ndarray) -> list[float]:
    gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (48, 48))
    hist = cv2.calcHist([resized], [0], None, [32], [0, 256]).flatten()
    hist = hist / (np.linalg.norm(hist) + 1e-8)
    return hist.astype(np.float32).tolist()


def face_embedding(face_region: np.ndarray) -> list[float]:
    if face_recognition is not None:
        rgb = cv2.cvtColor(face_region, cv2.COLOR_BGR2RGB)
        enc = face_recognition.face_encodings(rgb)
        if enc:
            return enc[0].astype(np.float32).tolist()
    return _fallback_embedding(face_region)


def embedding_distance(a: list[float], b: list[float]) -> float:
    aa = np.array(a, dtype=np.float32)
    bb = np.array(b, dtype=np.float32)
    if aa.shape != bb.shape:
        # Different encoders can produce different lengths, align by hashing fallback.
        seed_a = hashlib.sha256(aa.tobytes()).digest()
        seed_b = hashlib.sha256(bb.tobytes()).digest()
        aa = np.frombuffer(seed_a, dtype=np.uint8).astype(np.float32) / 255.0
        bb = np.frombuffer(seed_b, dtype=np.uint8).astype(np.float32) / 255.0
    return float(np.linalg.norm(aa - bb))


def match_student(embedding: list[float], students: list[dict]) -> FaceMatch | None:
    from .config import HAS_FACE_RECOGNITION, FACE_MATCH_THRESHOLD_HIGH_QUALITY, FACE_MATCH_THRESHOLD_LIGHTWEIGHT

    if not students:
        return None

    target_emb = np.array(embedding, dtype=np.float32)
    same_dims = all(len(s["embedding"]) == len(embedding) for s in students)
    if same_dims:
        db_embeddings = np.array([s["embedding"] for s in students], dtype=np.float32)
        distances = np.linalg.norm(db_embeddings - target_emb, axis=1)
    else:
        distances = np.array(
            [embedding_distance(embedding, student["embedding"]) for student in students],
            dtype=np.float32,
        )

    best_idx = int(np.argmin(distances))
    min_dist = float(distances[best_idx])

    threshold = FACE_MATCH_THRESHOLD_HIGH_QUALITY if HAS_FACE_RECOGNITION else FACE_MATCH_THRESHOLD_LIGHTWEIGHT
    if min_dist > threshold:
        return None
    return FaceMatch(
        student_id=students[best_idx]["student_id"],
        student_name=students[best_idx]["name"],
        score=min_dist,
    )


def liveness_check(face_region: np.ndarray) -> tuple[bool, str]:
    gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    brightness = float(np.mean(gray))

    # 1) Blur check: reject low-quality printed-photo-like frames.
    dynamic_threshold = 28.0 if brightness > 50 else 18.0
    if blur_score < dynamic_threshold:
        return False, (
            "Image too blurry, please ensure good lighting "
            f"(blur={blur_score:.2f}, threshold={dynamic_threshold:.2f}, brightness={brightness:.2f})"
        )

    # 2) FFT high-frequency texture check: screen/print texture often spikes.
    dft = np.fft.fft2(gray)
    dft_shift = np.fft.fftshift(dft)
    magnitude_spectrum = 20 * np.log(np.abs(dft_shift) + 1)
    rows, cols = gray.shape
    crow, ccol = rows // 2, cols // 2
    magnitude_spectrum[crow - 30:crow + 30, ccol - 30:ccol + 30] = 0
    high_freq_score = float(np.mean(magnitude_spectrum))
    fft_threshold = 3000.0
    if high_freq_score > fft_threshold:
        return False, (
            "Suspicious texture detected (Anti-spoofing triggered) "
            f"(fft={high_freq_score:.2f}, threshold={fft_threshold:.2f})"
        )

    # 3) Saturation check: reject grayscale/washed replay frames.
    hsv = cv2.cvtColor(face_region, cv2.COLOR_BGR2HSV)
    saturation = float(np.mean(hsv[:, :, 1]))
    saturation_threshold = 10.0
    if saturation < saturation_threshold:
        return False, (
            "Abnormal color distribution "
            f"(saturation={saturation:.2f}, threshold={saturation_threshold:.2f})"
        )

    return True, "Liveness passed"


def preprocess_face_for_emotion(face_region: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(face_region, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(l_channel)
    merged = cv2.merge((enhanced_l, a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _refined_heuristic_emotion(face_region: np.ndarray) -> tuple[str, float, str]:
    hsv = cv2.cvtColor(face_region, cv2.COLOR_BGR2HSV)
    saturation = float(np.mean(hsv[:, :, 1]))
    value = float(np.mean(hsv[:, :, 2]))
    gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
    edge_density = float(np.mean(cv2.Canny(gray, 80, 160) > 0))

    if value < 70:
        return "sad", 52.0, "heuristic"
    if saturation > 95 and value > 135:
        return "happy", 55.0, "heuristic"
    if edge_density > 0.2 and saturation < 65:
        return "angry", 50.0, "heuristic"
    if value > 170 and edge_density > 0.17:
        return "surprised", 50.0, "heuristic"
    return "neutral", 48.0, "heuristic"


def analyze_emotion(face_region: np.ndarray) -> tuple[str, float, str]:
    processed_face = preprocess_face_for_emotion(face_region)
    h_emotion, h_confidence, _ = _refined_heuristic_emotion(processed_face)

    try:
        from deepface import DeepFace
        result = DeepFace.analyze(
            processed_face,
            actions=["emotion"],
            detector_backend="opencv",
            enforce_detection=False,
            align=True,
            silent=True,
        )
        payload = result[0] if isinstance(result, list) else result
        if payload:
            emotion_dict = payload.get("emotion", {})
            if emotion_dict:
                dominant_emotion = max(emotion_dict, key=emotion_dict.get)
                confidence = float(emotion_dict.get(dominant_emotion, 0.0))
                emotion_map = {
                    "happy": "happy",
                    "sad": "sad",
                    "angry": "angry",
                    "surprise": "surprised",
                    "neutral": "neutral",
                    "fear": "unknown",
                    "disgust": "unknown",
                }
                mapped = emotion_map.get(dominant_emotion, "unknown")
                if confidence < 40.0:
                    return h_emotion, h_confidence, "heuristic_fallback_low_deepface_confidence"

                # Weighted fusion: trust DeepFace more but keep heuristic signal.
                deepface_weight = 0.7
                heuristic_weight = 0.3
                if mapped == h_emotion:
                    fused_confidence = confidence * deepface_weight + h_confidence * heuristic_weight
                    return mapped, float(fused_confidence), "fused_same_label"

                deepface_score = confidence * deepface_weight
                heuristic_score = h_confidence * heuristic_weight
                if deepface_score >= heuristic_score:
                    return mapped, float(deepface_score), "fused_deepface_dominant"
                return h_emotion, float(heuristic_score), "fused_heuristic_dominant"
    except Exception:
        pass

    return h_emotion, h_confidence, "heuristic"
