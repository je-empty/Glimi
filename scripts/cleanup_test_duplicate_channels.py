"""test 커뮤니티 Discord 길드의 중복 채널 분석/정리.

PASS 1 (analyze): 같은 이름 채널 묶음 찾기, 각 그룹별 keeper (메시지 최다) 와
delete 대상 출력. 파괴적 작업 안 함.
PASS 2 (--apply): 분석 결과 그대로 실행 — 비-keeper 채널 삭제.

Usage:
  GLIMI_COMMUNITY=test .venv/bin/python scripts/cleanup_test_duplicate_channels.py
  GLIMI_COMMUNITY=test .venv/bin/python scripts/cleanup_test_duplicate_channels.py --apply
"""
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("GLIMI_COMMUNITY", "test")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# .env 로드
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / "communities" / "test" / ".env")
load_dotenv(ROOT / ".env")

import discord  # noqa: E402

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
APPLY = "--apply" in sys.argv

EXPECTED = {
    "mgr-system-log", "mgr-dashboard", "mgr-creator",
    "dm-장서윤", "dm-아스나",
    "internal-dm-서유나-윤하나",
}


async def main():
    if not TOKEN:
        print("[ERROR] DISCORD_BOT_TOKEN 없음")
        return 1

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            guild = client.guilds[0] if client.guilds else None
            if not guild:
                print("[ERROR] 길드 없음")
                await client.close()
                return
            print(f"길드: {guild.name} (id={guild.id})")

            # 채널 그룹화 — 이름 기준
            groups: dict[str, list[discord.TextChannel]] = defaultdict(list)
            for ch in guild.text_channels:
                groups[ch.name].append(ch)

            actions = []  # [(keeper, [delete_targets]), ...]
            for name, chs in sorted(groups.items()):
                if len(chs) <= 1:
                    continue
                # 메시지 카운트 — keeper 결정용
                counted = []
                for ch in chs:
                    cnt = 0
                    try:
                        async for _ in ch.history(limit=1000):
                            cnt += 1
                    except Exception as e:
                        print(f"  [warn] {name}/{ch.id} history 실패: {e}")
                    counted.append((ch, cnt))
                counted.sort(key=lambda x: x[1], reverse=True)
                keeper = counted[0][0]
                deletes = [c for c, _ in counted[1:]]
                print(f"\n[중복] {name} — 총 {len(chs)}개")
                for ch, cnt in counted:
                    flag = "✓ KEEP" if ch.id == keeper.id else "✗ DEL "
                    pos = ch.position
                    cat = ch.category.name if ch.category else "(no cat)"
                    print(f"   {flag} id={ch.id} msgs={cnt} pos={pos} cat={cat}")
                actions.append((keeper, deletes))

            # expected 에 없는 채널 (이름 자체가 부정합)
            unexpected = [ch for ch in guild.text_channels
                          if ch.name not in EXPECTED and (ch.category and ch.category.name.startswith("glimi"))]
            if unexpected:
                print(f"\n[알 수 없는 glimi 채널]")
                for ch in unexpected:
                    print(f"   ? id={ch.id} name={ch.name} cat={ch.category.name}")

            if not APPLY:
                print(f"\n=== DRY-RUN: 삭제 대상 총 {sum(len(d) for _, d in actions)}개. --apply 로 실행 ===")
                await client.close()
                return

            # APPLY
            print(f"\n=== APPLY: 비-keeper 채널 삭제 시작 ===")
            for keeper, deletes in actions:
                for ch in deletes:
                    try:
                        await ch.delete(reason="Glimi cleanup: 중복 채널 정리")
                        print(f"   삭제: {ch.name} id={ch.id}")
                    except Exception as e:
                        print(f"   삭제 실패 {ch.name} id={ch.id}: {e}")
            print("=== APPLY 완료 ===")

        finally:
            await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
