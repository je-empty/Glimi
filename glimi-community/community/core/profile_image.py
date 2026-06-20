"""Glimi-side bridge to `glimi_imagegen` package.

`src/glimi_imagegen/` 자체는 Glimi 도메인 (agent / community / db) 을 모름 — 영어 prompt
와 두 path 만 받음. 이 모듈은 그 사이를 연결하는 layer.

두 가지 호출 시나리오:
1. **기존 에이전트 redraw** (`generate_for_agent`): DB row 가 이미 있는 에이전트의
   profile_image_filename 을 새 이미지로 교체. 즉시 swap.
2. **신규 에이전트 deferred reveal** (`generate_for_pending_agent`): DB row 가 아직
   없는 에이전트 ID 로 파일만 저장. 호출 측이 이미지 생성 완료 후 _cmd_profile_create
   로 에이전트를 활성화하면서 profile_image_filename 을 함께 set. 6분 동안 에이전트가
   존재하지 않다가 이미지와 함께 한 번에 등장 — UX 자연스러움.

공통: 무거운 generation 을 executor 로 offload (이벤트 루프 블로킹 방지) +
동일 agent_id 동시 생성 차단 (per-agent asyncio lock).

Discord / webhook 갱신은 호출하는 쪽 책임 (decoupling).
"""
from __future__ import annotations

import asyncio
import os
from typing import Literal

from community import community, db, log_writer
from community.core.profile import invalidate_cache
from community.core.runtime import runtime


# 동일 agent 동시 생성 차단 (각 ~6분 GPU 점유, queue 누적 방지)
_per_agent_locks: dict[str, asyncio.Lock] = {}


def _lock_for(agent_id: str) -> asyncio.Lock:
    lock = _per_agent_locks.get(agent_id)
    if lock is None:
        lock = asyncio.Lock()
        _per_agent_locks[agent_id] = lock
    return lock


async def _generate_to_paths(
    agent_id: str,
    character_block: str,
    version: Literal["v2", "v3"],
    seed: int,
) -> dict:
    """순수 파일 생성 — DB 갱신 / runtime refresh 없음.

    `generate_for_agent` (기존) / `generate_for_pending_agent` (신규) 가 공유하는 코어.
    """
    from community.glimi_imagegen import generate_profile  # 무거운 import (torch) — lazy

    profile_image_filename = f"{agent_id}.png"
    full_filename = f"{agent_id}-full.png"
    dst_dir = community.get_profile_images_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    crop_path = str(dst_dir / profile_image_filename)
    full_path = str(dst_dir / full_filename)

    lock = _lock_for(agent_id)
    async with lock:
        log_writer.system(
            f"[profile_image] start agent={agent_id} version={version} seed={seed} "
            f"block={character_block[:60]!r}"
        )
        loop = asyncio.get_event_loop()

        def _blocking():
            return generate_profile(
                prompt=character_block,
                full_path=full_path,
                crop_path=crop_path,
                version=version,
                seed=seed,
            )

        result = await loop.run_in_executor(None, _blocking)

        log_writer.system(
            f"[profile_image] done agent={agent_id} crop={os.path.basename(crop_path)} "
            f"method={result.get('crop_method', '?')}"
        )

    return {
        "agent_id": agent_id,
        "crop_path": crop_path,
        "full_path": full_path,
        "version": version,
        "seed": seed,
        "crop_method": result.get("crop_method", "?"),
    }


async def generate_for_agent(
    agent_id: str,
    character_block: str,
    version: Literal["v2", "v3"] = "v3",
    seed: int = 42,
) -> dict:
    """기존 에이전트 redraw — 생성 후 DB 의 profile_image_filename / sample_source_file 갱신.

    M3 base 기준 ~6분 (LoRA 첫 로딩 시 +30-60초 추가).
    """
    result = await _generate_to_paths(agent_id, character_block, version, seed)

    # DB 업데이트 — sample_source_file 은 직접 생성이라 NULL.
    profile_image_filename = f"{agent_id}.png"
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE agents SET profile_image_filename=?, sample_source_file=NULL WHERE id=?",
            (profile_image_filename, agent_id),
        )
        conn.commit()
    finally:
        conn.close()

    invalidate_cache(agent_id)
    try:
        runtime.refresh_agent(agent_id)
    except Exception as e:
        log_writer.system(f"[profile_image] runtime.refresh_agent 실패 (무시): {e}")

    return result


async def generate_for_pending_agent(
    agent_id: str,
    character_block: str,
    version: Literal["v2", "v3"] = "v3",
    seed: int = 42,
) -> dict:
    """신규 에이전트용 — 파일만 저장, DB UPDATE 없음 (에이전트가 아직 DB 에 없음).

    호출 측 (예: tool_handlers._h_create_agent_with_image) 이 이 함수 완료 후 곧이어
    _cmd_profile_create 로 에이전트 활성화. profile JSON 의 profile_image_filename
    필드는 미리 `agent_id.png` 로 셋업해두고 _cmd_profile_create 에 넘기면 자동 적용.
    """
    return await _generate_to_paths(agent_id, character_block, version, seed)


__all__ = ["generate_for_agent", "generate_for_pending_agent"]
