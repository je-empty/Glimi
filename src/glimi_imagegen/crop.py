"""1:1 face-centered crop matching Glimi reference proportions.

Calibrated from 9 (full, crop) reference pairs in assets/:
  face_to_crop = 0.68  — face fills ~68% of crop side
  head_room    = 0.59  — face center at 59% from top
  horiz_off    = -0.08 — face center 8% left of crop center

If anime face is detected → crop centered on face.
If detection fails → heuristic fallback (face assumed at upper-center).
"""
from pathlib import Path
from typing import Tuple
import numpy as np
from PIL import Image
import cv2

CASCADE_PATH = Path(__file__).parent / "lbpcascade_animeface.xml"
_detector = None


def _detector_lazy():
    global _detector
    if _detector is None:
        _detector = cv2.CascadeClassifier(str(CASCADE_PATH))
    return _detector


def detect_anime_face(pil_img: Image.Image):
    """Return (cx, cy, fw) of largest anime face, or None."""
    arr = np.array(pil_img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    eq = cv2.equalizeHist(gray)
    H_img, W_img = arr.shape[:2]
    strategies = [
        (eq, 5, 60), (eq, 3, 50), (eq, 2, 40), (eq, 1, 30),
        (gray, 3, 50), (gray, 1, 40),
        (cv2.flip(eq, 1), 3, 50),
    ]
    for img, min_neighbors, min_size in strategies:
        faces = _detector_lazy().detectMultiScale(
            img, scaleFactor=1.1, minNeighbors=min_neighbors,
            minSize=(min_size, min_size),
        )
        if len(faces):
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            if img is not eq and img is not gray:  # flipped
                fx = W_img - (fx + fw)
            return fx + fw / 2, fy + fh / 2, fw
    return None


def _reflect_crop(img_arr: np.ndarray, left: int, top: int, side: int) -> np.ndarray:
    H, W = img_arr.shape[:2]
    out = np.zeros((side, side, img_arr.shape[2]), dtype=img_arr.dtype)
    src_x0, src_y0 = max(0, left), max(0, top)
    src_x1, src_y1 = min(W, left + side), min(H, top + side)
    dst_x0, dst_y0 = src_x0 - left, src_y0 - top
    dst_x1, dst_y1 = dst_x0 + (src_x1 - src_x0), dst_y0 + (src_y1 - src_y0)
    out[dst_y0:dst_y1, dst_x0:dst_x1] = img_arr[src_y0:src_y1, src_x0:src_x1]
    if dst_x0 > 0:
        out[:, :dst_x0] = out[:, dst_x0:dst_x0 * 2][:, ::-1]
    if dst_x1 < side:
        w = side - dst_x1
        out[:, dst_x1:] = out[:, dst_x1 - w:dst_x1][:, ::-1]
    if dst_y0 > 0:
        out[:dst_y0] = out[dst_y0:dst_y0 * 2][::-1]
    if dst_y1 < side:
        h = side - dst_y1
        out[dst_y1:] = out[dst_y1 - h:dst_y1][::-1]
    return out


def crop_1x1(
    pil_img: Image.Image,
    target_size: int = 1024,
    face_to_crop_ratio: float = 0.68,
    head_room_ratio: float = 0.59,
    horiz_off: float = -0.08,
) -> Tuple[Image.Image, str]:
    """Return (1024² PIL image, method) — method ∈ {"face", "heuristic"}.

    Args:
        pil_img: source PIL image (typically 832×1216 portrait).
        target_size: output side length (default 1024 — Glimi standard).
        face_to_crop_ratio: face width as fraction of crop side. Glimi ref 0.68.
        head_room_ratio: face center vertical position from top. Glimi ref 0.59.
        horiz_off: face center horizontal offset from crop center (fraction of side).
                   Glimi ref -0.08 (face slightly left of center).
    """
    W, H = pil_img.size
    face = detect_anime_face(pil_img)
    if face is not None:
        cx, cy, fw = face
        side = int(fw / face_to_crop_ratio)
        side = max(side, int(min(W, H) * 0.55))
        side = min(side, int(min(W, H) * 0.95))
        left = int(round(cx - side / 2 - horiz_off * side))
        top = int(round(cy - side * head_room_ratio))
        method = "face"
    else:
        side = int(min(W, H) * 0.77)
        side = min(side, W, H)
        cx_guess, cy_guess = W / 2, H * 0.32
        left = int(round(cx_guess - side / 2 - horiz_off * side))
        top = int(round(cy_guess - side * head_room_ratio))
        method = "heuristic"

    arr = np.array(pil_img.convert("RGB"))
    cropped_arr = _reflect_crop(arr, left, top, side)
    cropped = Image.fromarray(cropped_arr)
    return cropped.resize((target_size, target_size), Image.LANCZOS), method
