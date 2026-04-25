"""sync brake 발동 채널의 첫 N건 DB vs Discord 비교.

Usage: GLIMI_COMMUNITY=test .venv/bin/python scripts/diagnose_sync_divergence.py <channel_name> [N]
예: scripts/diagnose_sync_divergence.py dm-장서윤 10
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

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
CHANNEL = sys.argv[1] if len(sys.argv) > 1 else "dm-장서윤"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10


async def main():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            guild = client.guilds[0] if client.guilds else None
            ch = discord.utils.get(guild.text_channels, name=CHANNEL)
            if not ch:
                print(f"[ERROR] 채널 없음: {CHANNEL}")
                return

            # DB
            conn = db.get_conn()
            db_rows = [dict(r) for r in conn.execute(
                "SELECT * FROM conversations WHERE channel=? ORDER BY timestamp ASC, id ASC LIMIT ?",
                (CHANNEL, N)
            ).fetchall()]
            conn.close()

            # Discord — oldest_first
            dc_msgs = []
            async for m in ch.history(limit=N, oldest_first=True):
                dc_msgs.append(m)

            print(f"=== {CHANNEL} 첫 {N}건 비교 ===\n")
            print(f"{'idx':<4} {'DB(speaker)':<22} {'DB msg':<60} {'DC msg':<60}")
            print("-" * 150)
            for i in range(max(len(db_rows), len(dc_msgs))):
                db_row = db_rows[i] if i < len(db_rows) else None
                dc_msg = dc_msgs[i] if i < len(dc_msgs) else None
                db_text = (db_row['message'][:55] if db_row else "—")
                dc_text = (dc_msg.content[:55] if dc_msg else "—")
                db_speaker = (db_row['speaker'][:20] if db_row else "—")
                dc_author = dc_msg.author.display_name[:20] if dc_msg else "—"
                eq = "==" if db_row and dc_msg and (db_row['message'] == dc_msg.content) else "!="
                print(f"{i:<4} {db_speaker:<22} {db_text:<60} {eq} {dc_text:<60} (dc author: {dc_author})")
        finally:
            await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
