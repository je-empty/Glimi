"""
Project Chaos — Discord ↔ DB 동기화

디스코드 채널 상태와 DB를 정합:
1. 채널 동기화: 불필요한 디코 채널 삭제, 필요한 채널 생성 (카테고리별)
2. 메시지 동기화: 디코 메시지 → DB 보충 (LLM 토큰 소모 없음)

주의: 같은 토큰으로 두 클라이언트를 동시에 열 수 없으므로,
봇이 실행 중이면 먼저 중지해야 합니다.
"""
import asyncio
import traceback
from datetime import datetime
from typing import Optional, Callable

import discord as discord_lib

from src import db, community, log_writer


def _get_category_for_channel(ch_name: str) -> str:
    """채널 이름 → 디스코드 카테고리 이름"""
    if ch_name.startswith("mgr"):
        return "chaos-mgr"
    elif ch_name.startswith("internal-group-"):
        return "chaos-internal-group"
    elif ch_name.startswith("internal-dm-") or ch_name.startswith("internal-"):
        return "chaos-internal-dm"
    elif ch_name.startswith("group-"):
        return "chaos-group"
    elif ch_name.startswith("dm-"):
        return "chaos-dm"
    return "chaos"


def _get_token() -> Optional[str]:
    env_path = community.get_community_dir() / ".env"
    if not env_path.exists():
        return None
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                return val if val and val != "여기에_봇_토큰" else None
    return None


def _get_expected_channels() -> set[str]:
    """DB 기반으로 존재해야 할 chaos 채널 목록"""
    channels = set()
    agents = db.list_agents()
    for a in agents:
        if a["type"] == "mgr":
            channels.add("mgr-dashboard")
        elif a["type"] != "creator":
            channels.add(f"dm-{a['name']}")
    channels.add("mgr-creator")
    channels.add("mgr-system-log")

    overview = db.get_channel_overview()
    for ch in overview:
        channels.add(ch["channel"])
    return channels


async def sync_community(
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    token = _get_token()
    if not token:
        return {"ok": False, "error": "토큰 미설정"}

    result = {
        "ok": False,
        "channels_created": [],
        "channels_deleted": [],
        "messages_synced": 0,
        "errors": [],
    }

    intents = discord_lib.Intents.default()
    intents.guilds = True
    intents.message_content = True
    intents.members = True
    client = discord_lib.Client(intents=intents)

    def _progress(msg: str):
        log_writer.system(f"[Sync] {msg}")
        if on_progress:
            on_progress(msg)

    @client.event
    async def on_ready():
        try:
            if not client.guilds:
                result["error"] = "서버 없음"
                await client.close()
                return

            guild = client.guilds[0]
            _progress(f"서버 연결: {guild.name}")

            # chaos 카테고리들 내 모든 채널 수집
            chaos_categories = [c for c in guild.categories if c.name.startswith("chaos")]
            all_chaos_channels = []
            for cat in chaos_categories:
                for ch in cat.text_channels:
                    all_chaos_channels.append(ch)

            expected = _get_expected_channels()

            # ── 1. 채널 정리 (불필요 삭제 + 잘못된 카테고리 삭제 + 중복 삭제) ──
            _progress("채널 정리 중...")
            surviving = {}  # name → channel (올바른 카테고리에 있는 것만)
            for ch in all_chaos_channels:
                correct_cat = _get_category_for_channel(ch.name)
                if ch.name not in expected:
                    try:
                        await ch.delete(reason="Chaos Sync: 불필요")
                        result["channels_deleted"].append(ch.name)
                        _progress(f"  삭제: {ch.name}")
                    except Exception as e:
                        result["errors"].append(f"삭제 실패 ({ch.name}): {e}")
                elif ch.category and ch.category.name != correct_cat:
                    try:
                        await ch.delete(reason="Chaos Sync: 카테고리 재배치")
                        _progress(f"  재배치: {ch.name} ({ch.category.name} → 재생성)")
                    except Exception as e:
                        result["errors"].append(f"재배치 실패 ({ch.name}): {e}")
                elif ch.name not in surviving:
                    surviving[ch.name] = ch
                else:
                    try:
                        await ch.delete(reason="Chaos Sync: 중복")
                        _progress(f"  중복 삭제: {ch.name}")
                    except Exception:
                        pass

            # ── 2. 필요 채널 생성 (올바른 카테고리에) ──
            _progress("필요 채널 생성 중...")
            MGR_ORDER = ["mgr-system-log", "mgr-dashboard", "mgr-creator"]
            for ch_name in sorted(expected):
                if ch_name not in surviving:
                    try:
                        cat_name = _get_category_for_channel(ch_name)
                        cat = discord_lib.utils.get(guild.categories, name=cat_name)
                        if not cat:
                            cat = await guild.create_category(cat_name)
                        new_ch = await guild.create_text_channel(ch_name, category=cat)
                        surviving[ch_name] = new_ch
                        result["channels_created"].append(ch_name)
                        _progress(f"  생성: {ch_name}")
                    except Exception as e:
                        result["errors"].append(f"생성 실패 ({ch_name}): {e}")

            # ── 3. mgr 채널 순서 정렬 ──
            mgr_cat = discord_lib.utils.get(guild.categories, name="chaos-mgr")
            if mgr_cat:
                for i, name in enumerate(MGR_ORDER):
                    ch = surviving.get(name)
                    if ch:
                        try:
                            await ch.move(beginning=True, offset=i)
                            await asyncio.sleep(0.3)
                        except Exception:
                            pass

            # ── 4. 메시지 동기화 (Discord → DB) ──
            _progress("메시지 동기화 중...")
            synced = 0
            agents = {a["name"]: a["id"] for a in db.list_agents()}

            for ch_name, ch in surviving.items():
                recent = db.get_recent_messages(ch_name, limit=1)
                after = None
                if recent:
                    try:
                        after = datetime.fromisoformat(recent[0].get("timestamp", ""))
                    except (ValueError, TypeError):
                        pass

                try:
                    messages = []
                    async for msg in ch.history(limit=100, after=after, oldest_first=True):
                        if msg.author.bot and msg.webhook_id:
                            speaker = agents.get(msg.author.display_name)
                            if speaker:
                                messages.append((ch_name, speaker, msg.content, msg.created_at.isoformat()))
                        elif not msg.author.bot:
                            from src.core.profile import get_user_id
                            messages.append((ch_name, get_user_id(), msg.content, msg.created_at.isoformat()))

                    if messages:
                        conn = db.get_conn()
                        for channel, speaker, message, ts in messages:
                            exists = conn.execute(
                                "SELECT 1 FROM conversations WHERE channel=? AND speaker=? AND message=? LIMIT 1",
                                (channel, speaker, message),
                            ).fetchone()
                            if not exists:
                                conn.execute(
                                    "INSERT INTO conversations (channel, speaker, message, timestamp) VALUES (?, ?, ?, ?)",
                                    (channel, speaker, message, ts),
                                )
                                synced += 1
                        conn.commit()
                        conn.close()
                        _progress(f"  {ch_name}: +{synced}건")
                except discord_lib.Forbidden:
                    pass
                except Exception as e:
                    result["errors"].append(f"메시지 동기화 실패 ({ch_name}): {e}")

            result["messages_synced"] = synced

            # ── 5. 빈 카테고리 정리 ──
            _progress("빈 카테고리 정리 중...")
            # guild 상태 다시 읽기 (캐시 갱신)
            guild = client.guilds[0]
            for cat in list(guild.categories):
                if cat.name.startswith("chaos") and len(cat.text_channels) == 0 and len(cat.voice_channels) == 0:
                    try:
                        cat_name = cat.name
                        await cat.delete()
                        result["channels_deleted"].append(f"[카테고리] {cat_name}")
                        _progress(f"  카테고리 삭제: {cat_name}")
                    except Exception:
                        pass

            result["ok"] = True
            _progress(f"동기화 완료 (채널 +{len(result['channels_created'])} -{len(result['channels_deleted'])}, 메시지 +{synced})")

        except Exception as e:
            result["error"] = str(e)
            result["errors"].append(traceback.format_exc())
            log_writer.system(f"[Sync] 오류: {traceback.format_exc()}")
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=120)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        if not result["ok"]:
            result["error"] = "시간 초과"
    except discord_lib.LoginFailure:
        result["error"] = "유효하지 않은 토큰"
    except Exception as e:
        if not result["ok"]:
            result["error"] = str(e)

    return result


def run_sync(on_progress: Optional[Callable[[str], None]] = None) -> dict:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sync_community(on_progress))
    finally:
        loop.close()
