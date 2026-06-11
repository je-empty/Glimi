"""
시스템 사양 감지 + Elastic Memory 컨텍스트 권장값.

대시보드가 "이 서버 사양에 맞는 권장 컨텍스트(num_ctx)" 를 제시하는 데 사용.
크로스플랫폼 (macOS unified memory / Windows·Linux NVIDIA VRAM).

순수 stdlib + 선택적 nvidia-smi 호출만 — 외부 의존성 없음.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess

from src.core.context_budget import HARD_FLOOR, RECOMMENDED_MIN, DEFAULT_NUM_CTX

# 컨텍스트 티어 — 하/중/상 (실제 num_ctx 값 표시)
CONTEXT_TIERS = [
    {"key": "low", "label_ko": "하", "label_en": "Low", "num_ctx": RECOMMENDED_MIN,
     "note_ko": "저사양 / 페르소나 위주", "note_en": "Low spec / persona-focused"},
    {"key": "mid", "label_ko": "중", "label_en": "Mid", "num_ctx": DEFAULT_NUM_CTX,
     "note_ko": "권장 기본 — 매니저 포함 모두 여유", "note_en": "Recommended default"},
    {"key": "high", "label_ko": "상", "label_en": "High", "num_ctx": 16384,
     "note_ko": "긴 기억 보존 (메모리 2배)", "note_en": "Rich memory (2x)"},
]


def _total_ram_gb() -> float:
    """전체 시스템 RAM (GB)."""
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            b = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            return round(b / (1024 ** 3), 1)
    except Exception:
        pass
    # Windows fallback
    try:
        import ctypes

        class _MEMSTAT(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = _MEMSTAT()
        ms.dwLength = ctypes.sizeof(_MEMSTAT)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return round(ms.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        return 0.0


def _nvidia_vram_gb() -> float:
    """NVIDIA GPU 총 VRAM (GB). nvidia-smi 없으면 0."""
    if not shutil.which("nvidia-smi"):
        return 0.0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            # 여러 GPU 면 최대값 (단일 모델은 한 GPU 에 상주)
            mibs = [float(x) for x in out.stdout.split("\n") if x.strip()]
            return round(max(mibs) / 1024.0, 1) if mibs else 0.0
    except Exception:
        pass
    return 0.0


def detect() -> dict:
    """현재 서버 사양 감지.

    Returns:
      platform, ram_gb, vram_gb, accel(메모리 종류), usable_gb(모델이 쓸 수 있는 메모리)
    """
    sysname = platform.system()  # Darwin / Windows / Linux
    machine = platform.machine()
    ram = _total_ram_gb()
    vram = _nvidia_vram_gb()

    if vram > 0:
        accel = "nvidia_vram"
        usable = vram
    elif sysname == "Darwin" and machine in ("arm64", "aarch64"):
        accel = "apple_unified"   # 통합 메모리 — RAM 이 곧 GPU 메모리
        usable = ram
    else:
        accel = "cpu_or_unknown"
        usable = ram

    return {
        "platform": sysname,
        "machine": machine,
        "ram_gb": ram,
        "vram_gb": vram,
        "accel": accel,
        "usable_gb": usable,
    }


def recommend_num_ctx(specs: dict | None = None) -> dict:
    """사양 기준 권장 num_ctx 티어.

    근거: num_ctx 는 KV 캐시로 VRAM 을 먹는다 (8192 기준 모델당 ~+1GB, 16384 면 ~+2GB).
    모델(e4b ~10GB / iq3-26b ~13GB) 상주 후 남는 메모리로 컨텍스트를 키울 수 있다.
    """
    s = specs or detect()
    usable = s.get("usable_gb", 0.0)

    if usable >= 28:
        tier = "high"      # 16GB+ 헤드룸 — 16384 여유 (분리 구성도)
        reason_ko = f"가용 메모리 {usable:.0f}GB — 긴 컨텍스트 여유"
    elif usable >= 14:
        tier = "mid"       # 8192 권장 (모델 + KV)
        reason_ko = f"가용 메모리 {usable:.0f}GB — 기본 8192 적합"
    elif usable >= 8:
        tier = "low"       # 4096 — 페르소나 위주, KV 절약
        reason_ko = f"가용 메모리 {usable:.0f}GB — 컨텍스트 절약 권장"
    else:
        tier = "low"
        reason_ko = f"가용 메모리 {usable:.0f}GB — 최소 구성 (저사양)"

    tier_info = next(t for t in CONTEXT_TIERS if t["key"] == tier)
    return {
        "tier": tier,
        "num_ctx": tier_info["num_ctx"],
        "reason_ko": reason_ko,
        "specs": s,
    }


def tier_for_num_ctx(num_ctx: int) -> str:
    """num_ctx 값 → 가장 가까운 티어 key (UI 슬라이더 현재 위치 표시용)."""
    best = min(CONTEXT_TIERS, key=lambda t: abs(t["num_ctx"] - num_ctx))
    return best["key"]


def clamp_num_ctx(num_ctx: int) -> int:
    """하드 floor 적용."""
    return max(HARD_FLOOR, int(num_ctx))


# ── 커뮤니티별 Elastic Memory 설정 (community .env 의 GLIMI_OLLAMA_NUM_CTX) ──
# 봇이 src/bot/__init__.py 에서 community .env 를 load_dotenv(override=True) 하므로,
# 여기 쓴 값이 다음 봇 (재)기동 시 적용된다.

def _community_env_path(community_id: str):
    from pathlib import Path
    from src.community import COMMUNITIES_DIR
    return Path(COMMUNITIES_DIR) / community_id / ".env"


def read_community_num_ctx(community_id: str) -> int:
    """community .env 의 GLIMI_OLLAMA_NUM_CTX (없으면 기본)."""
    p = _community_env_path(community_id)
    if p.exists():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("GLIMI_OLLAMA_NUM_CTX="):
                    v = line.split("=", 1)[1].strip().strip("'").strip('"')
                    return clamp_num_ctx(int(v))
        except Exception:
            pass
    return DEFAULT_NUM_CTX


def write_community_num_ctx(community_id: str, num_ctx: int) -> int:
    """community .env 의 GLIMI_OLLAMA_NUM_CTX upsert (다른 라인 보존). clamp 후 저장값 반환."""
    val = clamp_num_ctx(num_ctx)
    p = _community_env_path(community_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, found = [], False
    for line in lines:
        if line.strip().startswith("GLIMI_OLLAMA_NUM_CTX="):
            out.append(f"GLIMI_OLLAMA_NUM_CTX={val}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append("# Elastic Memory — 컨텍스트 윈도우 (대시보드에서 조절)")
        out.append(f"GLIMI_OLLAMA_NUM_CTX={val}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return val


def elastic_memory_status(community_id: str) -> dict:
    """대시보드용 — 현재 설정 + 티어 목록 + 사양 + 권장값."""
    cur = read_community_num_ctx(community_id)
    rec = recommend_num_ctx()
    return {
        "community": community_id,
        "current_num_ctx": cur,
        "current_tier": tier_for_num_ctx(cur),
        "tiers": CONTEXT_TIERS,
        "specs": rec["specs"],
        "recommended_tier": rec["tier"],
        "recommended_num_ctx": rec["num_ctx"],
        "recommended_reason_ko": rec["reason_ko"],
        "hard_floor": HARD_FLOOR,
    }
