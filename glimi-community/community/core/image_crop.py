"""정사각형 센터 크롭 — discord-free 순수 PIL 스파인 (Phase 1.6).

구 `community/bot/commands.py` 의 아바타 처리에 중복돼 있던 1:1 center-crop +
다운스케일 로직을 한 곳으로 모음. discord 업로드/URL 저장은 commands.py 에 남겨두고
(Phase 6 에서 함께 삭제), 여기엔 플랫폼 중립 이미지 변환만 둔다.

로직은 commands.py 의 두 크롭 블록과 동일:
  open → RGBA 변환 → w≠h 면 짧은 쪽 기준 center-crop → size 초과 시 LANCZOS 리사이즈
  → PNG 저장.
"""
from __future__ import annotations


def crop_square(src: str, dst: str, size: int = 512) -> str:
    """``src`` 이미지를 1:1 정사각형으로 center-crop + 최대 ``size`` 로 다운스케일한 뒤
    ``dst`` 에 PNG 로 저장하고 ``dst`` 경로를 돌려준다.

    - 직사각형이면 짧은 변(min(w,h)) 기준으로 중앙 정사각형 크롭.
    - 크롭 후 한 변이 ``size`` 보다 크면 ``size``×``size`` 로 LANCZOS 리사이즈.
    - 항상 RGBA → PNG.

    PIL 은 lazy import (web 런타임엔 미설치 — 아바타/imagegen 경로에서만 호출).
    """
    from PIL import Image  # lazy — torch/imagegen 처럼 무거운 옵션 의존

    img = Image.open(src).convert("RGBA")
    w, h = img.size
    if w != h:
        crop = min(w, h)
        left = (w - crop) // 2
        top = (h - crop) // 2
        img = img.crop((left, top, left + crop, top + crop))
    if img.size[0] > size:
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    img.save(dst, "PNG")
    return dst


__all__ = ["crop_square"]
