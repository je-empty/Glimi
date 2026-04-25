"""장서윤 dm 채팅 로그 → 메모리 백필 (일회성).

기존 _try_l1_extract 파이프라인을 batch 단위로 반복 호출. L2/L3 rollup 도 마지막에 수행.
Usage: GLIMI_COMMUNITY=test .venv/bin/python scripts/backfill_memory_jangseoyun.py
"""
import os
import sys
import time

os.environ.setdefault("GLIMI_COMMUNITY", "test")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.core import memory as mem  # noqa: E402
from src import db  # noqa: E402


AGENT_ID = "agent-persona-001"
CHANNEL = "dm-장서윤"


# 백필 — CLI cold-start + 동시성 경쟁으로 30s 부족. 120s 로 확장.
_orig_call_claude = mem._call_claude


def _call_claude_long(prompt, model=mem.EXTRACTION_MODEL, timeout=120, system=""):
    return _orig_call_claude(prompt, model=model, timeout=120, system=system)


mem._call_claude = _call_claude_long


def _progress():
    latest = db.get_latest_memory(AGENT_ID, CHANNEL, level=1)
    last_id = latest["msg_id_to"] if latest else 0
    remaining = db.count_messages_after(CHANNEL, last_id)
    return last_id, remaining


def main():
    print(f"community: {os.environ['GLIMI_COMMUNITY']}")
    print(f"db path: {db._get_db_path()}")
    print(f"agent: {AGENT_ID}  channel: {CHANNEL}")

    agent = db.get_agent(AGENT_ID)
    if not agent:
        print(f"[ERROR] agent {AGENT_ID} not found")
        return 1
    print(f"agent name: {agent.get('name')}")

    last_id, remaining = _progress()
    print(f"start: last_msg_id={last_id} remaining={remaining}")

    batch_idx = 0
    while remaining >= mem.L1_BATCH_SIZE:
        batch_idx += 1
        before_last = last_id
        try:
            mem._try_l1_extract(AGENT_ID, CHANNEL)
        except Exception as e:
            print(f"[batch {batch_idx}] L1 extract failed: {e}")
            break
        last_id, remaining = _progress()
        if last_id == before_last:
            print(f"[batch {batch_idx}] no progress (last_id stuck at {last_id}) — stopping")
            break
        print(f"[batch {batch_idx}] last_msg_id: {before_last} → {last_id}  remaining={remaining}")
        time.sleep(0.2)

    print(f"\nL1 done. total batches: {batch_idx}")

    print("\n--- L2 rollup ---")
    try:
        mem._try_l2_rollup(AGENT_ID, CHANNEL)
        print("L2 rollup ok")
    except Exception as e:
        print(f"L2 rollup failed: {e}")

    print("\n--- L3 rollup ---")
    try:
        mem._try_l3_rollup(AGENT_ID, CHANNEL)
        print("L3 rollup ok")
    except Exception as e:
        print(f"L3 rollup failed: {e}")

    # Summary
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT level, count(*) c FROM memories WHERE agent_id=? AND channel=? GROUP BY level ORDER BY level",
        (AGENT_ID, CHANNEL),
    ).fetchall()
    conn.close()
    print(f"\nfinal memory counts:")
    for r in rows:
        print(f"  L{r['level']}: {r['c']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
