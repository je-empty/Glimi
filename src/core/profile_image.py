"""Glimi-side bridge to `glimi_imagegen` package.

`src/glimi_imagegen/` 자체는 Glimi 도메인 (agent / community / db) 을 모름 — 영어 prompt
와 두 path 만 받음. 이 모듈은 그 사이를 연결하는 layer.

책임:
- agent_id → 커뮤니티 profile_images dir 의 두 file path 변환
- 무거운 generation 을 executor 로 offload (이벤트 루프 블로킹 방지)
- 완료 후 DB 업데이트 + profile cache invalidate + runtime.refresh_agent
- 동일 agent 동시 생성 방지 (per-agent asyncio lock)

Discord / webhook 갱신은 호출하는 쪽 책임 (decoupling).
"""
from __future__ import annotations

import asyncio
import os
from typing import Literal

from src import community, db, log_writer
from src.core.profile import invalidate_cache
from src.core.runtime import runtime


# 동일 agent 동시 생성 차단 (각 ~6분 GPU 점유, queue 누적 방지)
_per_agent_locks: dict[str, asyncio.Lock] = {}


def _lock_for(agent_id: str) -> asyncio.Lock:
    lock = _per_agent_locks.get(agent_id)
    if lock is None:
        lock = asyncio.Lock()
        _per_agent_locks[agent_id] = lock
    return lock


async def generate_for_agent(
    agent_id: str,
    character_block: str,
    version: Literal["v2", "v3"] = "v3",
    seed: int = 42,
) -> dict:
    """LoRA portrait 1장 생성 후 커뮤니티 profile_images dir 에 저장 + DB 업데이트.

    M3 base 기준 ~6분 (LoRA 첫 로딩 시 +30-60초 추가). executor 사용으로
    이벤트 루프 블로킹은 안 함.

    Args:
        agent_id: 대상 에이전트 (DB id).
        character_block: 영어 캐릭터 설명 (LoRA 가 영어로 학습됨).
            예: "korean female with high ponytail brown hair, ...".
            quality / glimistyle trigger / style suffix 는 패키지가 자동 wrap.
        version: "v3" (default, 신 캐릭) / "v2" (anchor 3 재현).
        seed: 재현용. 같은 (prompt, seed, version) → 동일 출력.

    Returns:
        {"agent_id", "crop_path", "full_path", "version", "seed", "crop_method"}.
    """
    from src.glimi_imagegen import generate_profile  # 무거운 import (torch) — lazy

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

        # DB 업데이트 — sample_source_file 은 직접 생성이라 NULL.
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


__all__ = ["generate_for_agent"]
