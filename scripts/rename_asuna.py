"""유키 아스나 → 아스나 rename + dm 채널 정리.

Usage: GLIMI_COMMUNITY=test .venv/bin/python scripts/rename_asuna.py [--apply]
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
OLD_NAME = "유키 아스나"
NEW_NAME = "아스나"
OLD_CH_DB = "dm-유키 아스나"
OLD_CH_DC = "dm-유키-아스나"
NEW_CH = "dm-아스나"
APPLY = "--apply" in sys.argv
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")


def db_audit():
    conn = db.get_conn()
    a = conn.execute("SELECT name FROM agents WHERE id=?", (AGENT_ID,)).fetchone()
    cv = conn.execute("SELECT count(*) c FROM conversations WHERE channel=?", (OLD_CH_DB,)).fetchone()["c"]
    ch = conn.execute("SELECT count(*) c FROM channels WHERE channel=?", (OLD_CH_DB,)).fetchone()["c"]
    conn.close()
    return {"agent_name": a["name"] if a else None, "conv": cv, "channel_row": ch}


def db_rename():
    conn = db.get_conn()
    conn.execute("UPDATE agents SET name=? WHERE id=?", (NEW_NAME, AGENT_ID))
    conn.execute("UPDATE conversations SET channel=? WHERE channel=?", (NEW_CH, OLD_CH_DB))
    conn.execute("UPDATE channels SET channel=? WHERE channel=?", (NEW_CH, OLD_CH_DB))
    # 관계 템플릿의 pet_name 등 굳이 안 건드림
    conn.commit()
    conn.close()


async def discord_rename():
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
            ch = discord.utils.get(guild.text_channels, name=OLD_CH_DC) \
                or discord.utils.get(guild.text_channels, name=OLD_CH_DB)
            if not ch:
                # 다른 변형도 시도
                for name in (OLD_CH_DC, OLD_CH_DB, "dm-유키-아스나", "dm-유키 아스나"):
                    ch = discord.utils.get(guild.text_channels, name=name)
                    if ch:
                        break
            if ch:
                print(f"discord 채널: {ch.name} (id={ch.id})")
                if APPLY:
                    await ch.edit(name=NEW_CH, reason="Glimi cleanup: 유키 아스나 → 아스나")
                    print(f"  rename → {NEW_CH}")
                else:
                    print(f"  [dry-run] rename → {NEW_CH}")
            else:
                print(f"[!] discord 채널 없음 (이미 rename 됐거나 삭제됨)")
        finally:
            await client.close()

    await client.start(TOKEN)


def main():
    print(f"=== {'APPLY' if APPLY else 'DRY-RUN'} ===")
    print(f"DB 영향:")
    audit = db_audit()
    for k, v in audit.items():
        print(f"  {k}: {v}")
    if APPLY:
        db_rename()
        print(f"\nDB rename 완료")
        after = db_audit()
        print(f"  최종 agent name: {after['agent_name']}")
    print("\n--- Discord ---")
    asyncio.run(discord_rename())


if __name__ == "__main__":
    main()
