"""아스나 (agent-persona-002) 완전 제거 — DB + Discord + 프로필 이미지 + 다른 에이전트의 아스나 언급.

Usage: GLIMI_COMMUNITY=test .venv/bin/python scripts/remove_asuna.py [--apply]
DRY-RUN 기본. --apply 로 실제 삭제.
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("GLIMI_COMMUNITY", "test")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / "communities" / "test" / ".env")
load_dotenv(ROOT / ".env")

import discord  # noqa: E402
from src import db  # noqa: E402

AGENT_ID = "agent-persona-002"
NAME = "아스나"
CHANNEL = "dm-아스나"
APPLY = "--apply" in sys.argv
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")


def db_audit():
    conn = db.get_conn()
    counts = {}
    counts["agents"] = conn.execute("SELECT count(*) c FROM agents WHERE id=?", (AGENT_ID,)).fetchone()["c"]
    counts["conv_dm"] = conn.execute("SELECT count(*) c FROM conversations WHERE channel=?", (CHANNEL,)).fetchone()["c"]
    counts["conv_other_mention"] = conn.execute(
        "SELECT count(*) c FROM conversations WHERE channel != ? AND (message LIKE ? OR speaker = ?)",
        (CHANNEL, f"%{NAME}%", AGENT_ID)
    ).fetchone()["c"]
    counts["memories"] = conn.execute(
        "SELECT count(*) c FROM memories WHERE agent_id = ? OR content LIKE ? OR related_entities LIKE ? OR related_agent_id = ?",
        (AGENT_ID, f"%{NAME}%", f"%{NAME}%", AGENT_ID)
    ).fetchone()["c"]
    counts["facts"] = conn.execute(
        "SELECT count(*) c FROM agent_facts WHERE agent_id = ? OR subject = ? OR object = ?",
        (AGENT_ID, NAME, NAME)
    ).fetchone()["c"]
    counts["rels"] = conn.execute(
        "SELECT count(*) c FROM relationships WHERE agent_a = ? OR agent_b = ?",
        (AGENT_ID, AGENT_ID)
    ).fetchone()["c"]
    counts["channels"] = conn.execute("SELECT count(*) c FROM channels WHERE channel=?", (CHANNEL,)).fetchone()["c"]
    counts["satellites"] = sum(
        conn.execute(f"SELECT count(*) c FROM {t} WHERE agent_id = ?", (AGENT_ID,)).fetchone()["c"]
        for t in ("agent_personality", "agent_appearance", "agent_daily_life",
                  "agent_speech", "agent_config", "agent_relationship_templates")
    )
    conn.close()
    return counts


def db_purge():
    conn = db.get_conn()
    # 위성 테이블
    for t in ("agent_personality", "agent_appearance", "agent_daily_life",
              "agent_speech", "agent_config", "agent_relationship_templates"):
        conn.execute(f"DELETE FROM {t} WHERE agent_id = ?", (AGENT_ID,))
    # facts, memories, relationships, conversations
    conn.execute("DELETE FROM agent_facts WHERE agent_id = ? OR subject = ? OR object = ?",
                 (AGENT_ID, NAME, NAME))
    conn.execute("DELETE FROM memories WHERE agent_id = ? OR content LIKE ? OR related_entities LIKE ? OR related_agent_id = ?",
                 (AGENT_ID, f"%{NAME}%", f"%{NAME}%", AGENT_ID))
    conn.execute("DELETE FROM relationship_history WHERE agent_a = ? OR agent_b = ?",
                 (AGENT_ID, AGENT_ID))
    conn.execute("DELETE FROM relationships WHERE agent_a = ? OR agent_b = ?",
                 (AGENT_ID, AGENT_ID))
    # 모든 채널의 아스나 관련 발화 + dm-아스나 전체 + agent-persona-002 발화
    conn.execute(
        "DELETE FROM conversations WHERE channel = ? OR speaker = ? OR message LIKE ?",
        (CHANNEL, AGENT_ID, f"%{NAME}%")
    )
    # 채널 메타 + 에이전트
    conn.execute("DELETE FROM channels WHERE channel = ?", (CHANNEL,))
    conn.execute("DELETE FROM agents WHERE id = ?", (AGENT_ID,))
    conn.commit()
    conn.close()


def fs_purge():
    """프로필 이미지 + JSON 파일 정리."""
    from src import community as _comm
    profile_dir = _comm.get_profile_images_dir()
    deleted = []
    for p in profile_dir.glob(f"{AGENT_ID}*"):
        if APPLY:
            p.unlink()
        deleted.append(str(p))
    # legacy JSON profile dir
    profiles_json = ROOT / "communities" / "test" / "profiles" / f"{AGENT_ID}.json"
    if profiles_json.exists():
        if APPLY:
            profiles_json.unlink()
        deleted.append(str(profiles_json))
    return deleted


async def discord_purge():
    if not TOKEN:
        print("[ERROR] DISCORD_BOT_TOKEN 없음")
        return
    intents = discord.Intents.default()
    intents.guilds = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            guild = client.guilds[0] if client.guilds else None
            if not guild:
                print("[ERROR] 길드 없음")
                return
            ch = discord.utils.get(guild.text_channels, name=CHANNEL)
            if ch:
                print(f"discord 채널 발견: {ch.name} (id={ch.id})")
                if APPLY:
                    await ch.delete(reason="Glimi cleanup: 아스나 제거")
                    print("  삭제 완료")
                else:
                    print("  [dry-run] 삭제 예정")
            else:
                print(f"discord 채널 없음: {CHANNEL}")
        finally:
            await client.close()

    await client.start(TOKEN)


def main():
    print(f"=== 아스나 제거 ({'APPLY' if APPLY else 'DRY-RUN'}) ===\n")

    print("DB 영향 범위:")
    audit = db_audit()
    for k, v in audit.items():
        print(f"  {k}: {v}")

    if APPLY:
        print("\n--- DB purge ---")
        db_purge()
        after = db_audit()
        print("DB 정리 후:")
        for k, v in after.items():
            print(f"  {k}: {v}")

    print("\n--- 파일 시스템 ---")
    deleted = fs_purge()
    for p in deleted:
        print(f"  {'삭제됨' if APPLY else '[dry-run] 삭제 예정'}: {p}")

    print("\n--- Discord ---")
    asyncio.run(discord_purge())

    print(f"\n=== {'완료' if APPLY else 'DRY-RUN 완료. --apply 로 실행'} ===")


if __name__ == "__main__":
    main()
