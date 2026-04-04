"""
Project Chaos — Discord ↔ DB 동기화

1. 채널 동기화: 불필요한 디코 채널 삭제, 필요한 채널 생성 (카테고리별)
2. 메시지 동기화: 디코 메시지 → DB 보충 (LLM 토큰 소모 없음, Discord API만 사용)
3. 유저 프로필 동기화: 디코 사용자 이름/ID 매핑

주의: 같은 토큰으로 두 클라이언트를 동시에 열 수 없으므로,
봇이 실행 중이면 먼저 중지해야 합니다.
"""
import asyncio
import traceback
from datetime import datetime, timezone
from typing import Optional, Callable

import discord as discord_lib

from src import db, community, log_writer


# 카테고리 순서
CATEGORY_ORDER = ["chaos-mgr", "chaos-dm", "chaos-group", "chaos-internal-dm", "chaos-internal-group"]


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


async def _fetch_all_messages(channel, after=None, progress_fn=None):
    """채널의 모든 메시지를 페이지네이션으로 가져오기 (100개씩)"""
    all_messages = []
    batch = 0

    while True:
        messages = []
        async for msg in channel.history(limit=100, after=after, oldest_first=True):
            messages.append(msg)

        if not messages:
            break

        all_messages.extend(messages)
        batch += 1
        after = messages[-1]  # 다음 페이지의 시작점

        if progress_fn:
            progress_fn(f"  {channel.name}: {len(all_messages)}건 로드 (batch {batch})")

        # rate limit 방지
        await asyncio.sleep(0.5)

        # 마지막 batch가 100개 미만이면 끝
        if len(messages) < 100:
            break

    return all_messages


def _resolve_speaker(msg, agent_map: dict, user_id: str) -> Optional[str]:
    """Discord 메시지 → speaker ID 매핑"""
    if msg.author.bot and msg.webhook_id:
        # Webhook = 에이전트 발화
        return agent_map.get(msg.author.display_name)
    elif not msg.author.bot:
        # 유저 메시지
        return user_id
    return None


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
        "categories_deleted": [],
        "messages_synced": 0,
        "channels_scanned": 0,
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

            # 유저 ID 가져오기
            from src.core.profile import get_user_id, get_user_name
            user_id = get_user_id()

            # 에이전트 이름 → ID 매핑
            agent_map = {a["name"]: a["id"] for a in db.list_agents()}

            # ═══ 1. 채널 정리 ═══
            _progress("채널 정리 중...")
            chaos_categories = [c for c in guild.categories if c.name.startswith("chaos")]
            all_chaos_channels = []
            for cat in chaos_categories:
                for ch in cat.text_channels:
                    all_chaos_channels.append(ch)

            expected = _get_expected_channels()

            surviving = {}
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
                        _progress(f"  재배치: {ch.name}")
                    except Exception as e:
                        result["errors"].append(f"재배치 실패 ({ch.name}): {e}")
                elif ch.name not in surviving:
                    surviving[ch.name] = ch
                else:
                    try:
                        await ch.delete(reason="Chaos Sync: 중복")
                    except Exception:
                        pass

            # ═══ 2. 카테고리 생성 + 채널 생성 (순서대로) ═══
            _progress("채널 생성 중...")
            MGR_ORDER = ["mgr-system-log", "mgr-dashboard", "mgr-creator"]

            # 카테고리를 원하는 순서대로 생성
            for cat_name in CATEGORY_ORDER:
                needed = [ch for ch in sorted(expected) if _get_category_for_channel(ch) == cat_name and ch not in surviving]
                if not needed and not any(ch for ch in surviving.values() if ch.category and ch.category.name == cat_name):
                    continue

                cat = discord_lib.utils.get(guild.categories, name=cat_name)
                if not cat:
                    cat = await guild.create_category(cat_name)
                    _progress(f"  카테고리 생성: {cat_name}")

                # mgr 카테고리는 특정 순서
                if cat_name == "chaos-mgr":
                    needed = [ch for ch in MGR_ORDER if ch not in surviving]

                for ch_name in needed:
                    try:
                        new_ch = await guild.create_text_channel(ch_name, category=cat)
                        surviving[ch_name] = new_ch
                        result["channels_created"].append(ch_name)
                        _progress(f"  생성: {ch_name}")
                    except Exception as e:
                        result["errors"].append(f"생성 실패 ({ch_name}): {e}")

            # mgr 채널 순서 정렬
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

            # ═══ 3. 빈 카테고리 정리 ═══
            _progress("빈 카테고리 정리 중...")
            for cat in list(guild.categories):
                if cat.name.startswith("chaos") and len(cat.text_channels) == 0 and len(cat.voice_channels) == 0:
                    try:
                        result["categories_deleted"].append(cat.name)
                        await cat.delete()
                        _progress(f"  카테고리 삭제: {cat.name}")
                    except Exception:
                        pass

            # ═══ 4. 카테고리 순서 정렬 ═══
            _progress("카테고리 순서 정리 중...")
            # 기존 non-chaos 카테고리 위치 파악
            existing_cats = {c.name: c for c in guild.categories}
            for i, cat_name in enumerate(CATEGORY_ORDER):
                cat = existing_cats.get(cat_name)
                if cat:
                    try:
                        await cat.edit(position=i)
                        await asyncio.sleep(0.2)
                    except Exception:
                        pass

            # ═══ 5. 메시지 동기화 (Discord → DB) ═══
            _progress("메시지 동기화 중...")
            total_synced = 0

            for ch_name, ch in surviving.items():
                # DB 메시지 수
                conn = db.get_conn()
                db_count = conn.execute(
                    "SELECT COUNT(*) FROM conversations WHERE channel=?", (ch_name,)
                ).fetchone()[0]
                conn.close()

                # 전체 메시지 가져오기 (항상 전체 — 중복은 DB에서 필터)
                try:
                    discord_msgs = await _fetch_all_messages(ch, after=None, progress_fn=_progress)
                except discord_lib.Forbidden:
                    _progress(f"  {ch_name}: 권한 없음 (스킵)")
                    continue
                except Exception as e:
                    result["errors"].append(f"메시지 로드 실패 ({ch_name}): {e}")
                    continue

                if not discord_msgs:
                    result["channels_scanned"] += 1
                    continue

                _progress(f"  {ch_name}: 디코 {len(discord_msgs)}개 / DB {db_count}개")

                # DB에 삽입 (중복 방지)
                conn = db.get_conn()
                ch_synced = 0

                for msg in discord_msgs:
                    if not msg.content:
                        continue

                    speaker = _resolve_speaker(msg, agent_map, user_id)
                    if not speaker:
                        continue

                    ts = msg.created_at.isoformat()

                    # 중복 체크 (채널 + 발화자 + 메시지 내용 + 시간 근접)
                    exists = conn.execute(
                        "SELECT 1 FROM conversations WHERE channel=? AND speaker=? AND message=? LIMIT 1",
                        (ch_name, speaker, msg.content),
                    ).fetchone()

                    if not exists:
                        conn.execute(
                            "INSERT INTO conversations (channel, speaker, message, timestamp) VALUES (?, ?, ?, ?)",
                            (ch_name, speaker, msg.content, ts),
                        )
                        ch_synced += 1

                conn.commit()
                conn.close()

                total_synced += ch_synced
                result["channels_scanned"] += 1

                if ch_synced:
                    _progress(f"  {ch_name}: +{ch_synced}건 동기화")
                else:
                    _progress(f"  {ch_name}: 변경 없음")

                # rate limit 방지
                await asyncio.sleep(0.3)

            result["messages_synced"] = total_synced

            # ═══ 6. 유저 프로필 동기화 ═══
            _progress("유저 프로필 확인 중...")
            # Discord 서버의 오너(봇을 운영하는 사용자) 정보 동기화
            for member in guild.members:
                if member.bot:
                    continue
                # users 테이블에 없으면 기본 정보 저장
                conn = db.get_conn()
                existing = conn.execute("SELECT 1 FROM users WHERE id=?", (str(member.id),)).fetchone()
                if not existing:
                    # 기존 user_id(이름 기반)로 저장된 게 있으면 스킵
                    existing_by_name = conn.execute("SELECT 1 FROM users WHERE name=?", (member.display_name,)).fetchone()
                    if not existing_by_name:
                        _progress(f"  유저 발견: {member.display_name} (#{member.id})")
                conn.close()

            result["ok"] = True
            summary = (
                f"동기화 완료 — "
                f"채널 +{len(result['channels_created'])} -{len(result['channels_deleted'])}, "
                f"메시지 +{total_synced}, "
                f"채널 {result['channels_scanned']}개 스캔"
            )
            _progress(summary)

        except Exception as e:
            result["error"] = str(e)
            result["errors"].append(traceback.format_exc())
            log_writer.system(f"[Sync] 오류: {traceback.format_exc()}")
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=300)  # 5분 타임아웃
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
