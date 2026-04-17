"""
Project Glimi — Discord ↔ DB 동기화

1. 채널 동기화: 불필요한 Discord 채널 삭제, 필요한 채널 생성 (카테고리별)
2. 메시지 동기화: Discord 메시지 → DB 보충 (LLM 토큰 소모 없음, Discord API만 사용)
3. 오너 프로필 동기화: Discord 오너 이름/ID 매핑

주의: 같은 토큰으로 두 클라이언트를 동시에 열 수 없으므로,
봇이 실행 중이면 먼저 중지해야 합니다.
"""
import asyncio
import os
import traceback
from datetime import datetime, timezone
from typing import Optional, Callable

import discord as discord_lib

from src import db, community, log_writer


def _sync_error_log(msg: str):
    """sync 에러를 runtime_error.log에 기록"""
    log_writer.error(f"[Sync] {msg}")


# 카테고리 순서
CATEGORY_ORDER = ["glimi-mgr", "glimi-dm", "glimi-group", "glimi-internal-dm", "glimi-internal-group"]


def _get_category_for_channel(ch_name: str) -> str:
    """채널 이름 → 디스코드 카테고리 이름"""
    if ch_name.startswith("mgr"):
        return "glimi-mgr"
    elif ch_name.startswith("internal-group-"):
        return "glimi-internal-group"
    elif ch_name.startswith("internal-dm-") or ch_name.startswith("internal-"):
        return "glimi-internal-dm"
    elif ch_name.startswith("group-"):
        return "glimi-group"
    elif ch_name.startswith("dm-"):
        return "glimi-dm"
    return "glimi"


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
    """DB 기반으로 존재해야 할 glimi 채널 목록"""
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
        # 오너 메시지
        return user_id
    return None


async def sync_community(
    on_progress: Optional[Callable[[str], None]] = None,
    channels_filter: Optional[set[str]] = None,
) -> dict:
    """
    channels_filter: 지정하면 해당 채널만 메시지 동기화 (채널 구조는 항상 전체 싱크)
    """
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

            # 오너 ID 가져오기
            from src.core.profile import get_user_id, get_user_name
            user_id = get_user_id()
            user_name = get_user_name()

            # 에이전트 매핑
            all_agents = db.list_agents()
            agent_map = {a["name"]: a["id"] for a in all_agents}  # name→id (Discord→DB용)
            agents_by_id = {a["id"]: a for a in all_agents}       # id→agent (DB→Discord용)

            # ═══ 1. 채널 정리 ═══
            _progress("채널 정리 중...")
            glimi_categories = [c for c in guild.categories if c.name.startswith("glimi")]
            all_glimi_channels = []
            for cat in glimi_categories:
                for ch in cat.text_channels:
                    all_glimi_channels.append(ch)

            expected = _get_expected_channels()

            surviving = {}
            for ch in all_glimi_channels:
                correct_cat = _get_category_for_channel(ch.name)
                if ch.name not in expected:
                    try:
                        await ch.delete(reason="Glimi Sync: 불필요")
                        result["channels_deleted"].append(ch.name)
                        _progress(f"  삭제: {ch.name}")
                    except Exception as e:
                        result["errors"].append(f"삭제 실패 ({ch.name}): {e}")
                elif ch.category and ch.category.name != correct_cat:
                    # 카테고리 이동 (삭제하지 않음 — 메시지 보존)
                    try:
                        target_cat = discord_lib.utils.get(guild.categories, name=correct_cat)
                        if not target_cat:
                            target_cat = await guild.create_category(correct_cat)
                        await ch.edit(category=target_cat)
                        surviving[ch.name] = ch
                        _progress(f"  이동: {ch.name} → {correct_cat}")
                    except Exception as e:
                        result["errors"].append(f"이동 실패 ({ch.name}): {e}")
                        surviving[ch.name] = ch  # 실패해도 유지
                elif ch.name not in surviving:
                    surviving[ch.name] = ch
                else:
                    try:
                        await ch.delete(reason="Glimi Sync: 중복")
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
                if cat_name == "glimi-mgr":
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
            mgr_cat = discord_lib.utils.get(guild.categories, name="glimi-mgr")
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
                if cat.name.startswith("glimi") and len(cat.text_channels) == 0 and len(cat.voice_channels) == 0:
                    try:
                        result["categories_deleted"].append(cat.name)
                        await cat.delete()
                        _progress(f"  카테고리 삭제: {cat.name}")
                    except Exception:
                        pass

            # ═══ 4. 카테고리 순서 정렬 ═══
            _progress("카테고리 순서 정리 중...")
            # 기존 non-glimi 카테고리 위치 파악
            existing_cats = {c.name: c for c in guild.categories}
            for i, cat_name in enumerate(CATEGORY_ORDER):
                cat = existing_cats.get(cat_name)
                if cat:
                    try:
                        await cat.edit(position=i)
                        await asyncio.sleep(0.2)
                    except Exception:
                        pass

            # ═══ 5. 양방향 메시지 동기화 ═══
            _progress("메시지 동기화 중...")
            total_discord_to_db = 0
            total_db_to_discord = 0

            # 아바타 로드 함수
            from src.bot.core import _get_avatar_bytes

            for ch_name in list(surviving.keys()):
                ch = surviving[ch_name]
                # 채널 필터 적용
                if channels_filter and ch_name not in channels_filter:
                    continue

                conn = db.get_conn()
                db_count = conn.execute(
                    "SELECT COUNT(*) FROM conversations WHERE channel=?", (ch_name,)
                ).fetchone()[0]
                conn.close()

                # Discord 메시지 내용 가져오기 (전체)
                discord_msgs = []
                try:
                    discord_msgs = await _fetch_all_messages(ch, after=None, progress_fn=_progress)
                except discord_lib.Forbidden:
                    _progress(f"  {ch_name}: 권한 없음 (스킵)")
                    result["channels_scanned"] += 1
                    continue
                except Exception as e:
                    result["errors"].append(f"메시지 로드 실패 ({ch_name}): {e}")

                discord_count = len(discord_msgs)
                _progress(f"  {ch_name}: Discord {discord_count} / DB {db_count}")

                # DB가 기준 — Discord에 DB보다 많은 메시지가 있으면 정리
                if discord_count > db_count and discord_msgs:
                    # DB에 있는 메시지 내용 set
                    conn = db.get_conn()
                    db_messages = set()
                    for row in conn.execute(
                        "SELECT message FROM conversations WHERE channel=?", (ch_name,)
                    ).fetchall():
                        db_messages.add(row[0])
                    conn.close()

                    # 삭제 대상 수 계산
                    to_delete = [msg for msg in discord_msgs if msg.content and msg.content not in db_messages]

                    if to_delete:
                        # DB가 비어있거나 삭제할 메시지가 많으면 채널 재생성이 효율적
                        if db_count == 0 or len(to_delete) > 20:
                            _progress(f"  {ch_name}: 메시지 {len(to_delete)}건 정리 — 채널 재생성")
                            cat = ch.category
                            position = ch.position
                            try:
                                await ch.delete(reason="Glimi Sync: 채널 재생성 (효율적 정리)")
                                new_ch = await guild.create_text_channel(ch_name, category=cat)
                                try:
                                    await new_ch.move(beginning=True, offset=position)
                                except Exception:
                                    pass
                                surviving[ch_name] = new_ch
                                ch = new_ch
                                discord_msgs = []
                                discord_count = 0
                                total_discord_to_db += len(to_delete)
                                _progress(f"  {ch_name}: 채널 재생성 완료")
                            except Exception as e:
                                result["errors"].append(f"채널 재생성 실패 ({ch_name}): {e}")
                        else:
                            # 소량이면 개별 삭제
                            deleted = 0
                            for msg in to_delete:
                                try:
                                    await msg.delete()
                                    deleted += 1
                                    await asyncio.sleep(0.5)
                                except Exception:
                                    pass
                            if deleted:
                                total_discord_to_db += deleted
                                _progress(f"  {ch_name}: Discord 메시지 {deleted}건 삭제 (DB 기준)")

                # ── DB → Discord (DB에 있는데 Discord에 없는 메시지 복원) ──
                if db_count > 0 and db_count > discord_count:
                    need = db_count - discord_count
                    _progress(f"  {ch_name}: DB→Discord 복원 ({need}건 누락)...")

                    # Discord에 이미 있는 메시지 내용 set (중복 방지)
                    discord_contents = set()
                    for dm in discord_msgs:
                        if dm.content:
                            discord_contents.add(dm.content)

                    conn = db.get_conn()
                    messages = [dict(r) for r in conn.execute(
                        "SELECT * FROM conversations WHERE channel=? ORDER BY timestamp ASC",
                        (ch_name,)
                    ).fetchall()]
                    conn.close()

                    # Discord에 없는 메시지만 필터
                    to_send = [m for m in messages if m["message"] not in discord_contents]
                    _progress(f"  {ch_name}: {len(to_send)}건 전송 예정")

                    webhooks = {}
                    sent = 0
                    for msg in to_send:
                        speaker_id = msg["speaker"]
                        content = msg["message"]

                        if speaker_id == user_id:
                            display_name = user_name
                            avatar = None
                        elif speaker_id in agents_by_id:
                            display_name = agents_by_id[speaker_id]["name"]
                            avatar = _get_avatar_bytes(speaker_id)
                        else:
                            display_name = speaker_id
                            avatar = None

                        wh_key = display_name
                        if wh_key not in webhooks:
                            wh_name = f"glimi-{speaker_id}" if speaker_id in agents_by_id else f"glimi-user"
                            existing_whs = await ch.webhooks()
                            wh = next((w for w in existing_whs if w.name == wh_name), None)
                            if not wh:
                                wh = await ch.create_webhook(name=wh_name, avatar=avatar)
                            webhooks[wh_key] = wh

                        try:
                            await webhooks[wh_key].send(content=content, username=display_name)
                            sent += 1
                            if sent % 20 == 0:
                                _progress(f"  {ch_name}: {sent}/{len(to_send)}건")
                            await asyncio.sleep(0.5)
                        except discord_lib.HTTPException as e:
                            if e.status == 429:
                                retry = getattr(e, 'retry_after', 10)
                                _progress(f"  rate limit — {retry:.0f}초 대기")
                                await asyncio.sleep(retry + 1)
                                try:
                                    await webhooks[wh_key].send(content=content, username=display_name)
                                    sent += 1
                                except Exception:
                                    result["errors"].append(f"재시도 실패 ({ch_name} #{msg.get('id','')})")
                            else:
                                result["errors"].append(f"DB→Discord ({ch_name}): {e}")
                                await asyncio.sleep(2)
                        except Exception as e:
                            result["errors"].append(f"DB→Discord ({ch_name} #{msg.get('id','')}): {e}")
                            await asyncio.sleep(2)

                    total_db_to_discord += sent
                    _progress(f"  {ch_name}: DB→Discord {sent}건 복원 완료")

                result["channels_scanned"] += 1
                await asyncio.sleep(0.3)

            result["messages_deleted_from_discord"] = total_discord_to_db
            result["messages_restored"] = total_db_to_discord

            # ═══ 6. 오너 프로필 동기화 ═══
            _progress("오너 프로필 확인 중...")
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
                        _progress(f"  오너 발견: {member.display_name} (#{member.id})")
                conn.close()

            result["ok"] = True
            summary = (
                f"동기화 완료 — "
                f"채널 +{len(result['channels_created'])} -{len(result['channels_deleted'])}, "
                f"Discord→DB +{total_discord_to_db}, DB→Discord +{total_db_to_discord}, "
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
        await asyncio.wait_for(client.start(token), timeout=1800)  # 30분 타임아웃
    except (asyncio.CancelledError, asyncio.TimeoutError):
        if not result["ok"]:
            result["error"] = "시간 초과"
    except discord_lib.LoginFailure:
        result["error"] = "유효하지 않은 토큰"
    except Exception as e:
        if not result["ok"]:
            result["error"] = str(e)

    # 에러를 별도 로그 파일에 기록
    if result.get("errors") or result.get("error"):
        _sync_error_log(f"=== Sync {'완료' if result['ok'] else '실패'} ===")
        if result.get("error"):
            _sync_error_log(f"FATAL: {result['error']}")
        for err in result.get("errors", []):
            _sync_error_log(err)

    return result


def run_sync(
    on_progress: Optional[Callable[[str], None]] = None,
    channels_filter: Optional[set[str]] = None,
) -> dict:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sync_community(on_progress, channels_filter))
    finally:
        loop.close()


async def restore_messages(
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """DB → Discord: DB 메시지를 Webhook으로 디스코드에 복원"""
    token = _get_token()
    if not token:
        return {"ok": False, "error": "토큰 미설정"}

    result = {"ok": False, "restored": 0, "channels": 0, "errors": []}

    intents = discord_lib.Intents.default()
    intents.guilds = True
    intents.message_content = True
    client = discord_lib.Client(intents=intents)

    def _progress(msg):
        log_writer.system(f"[Restore] {msg}")
        if on_progress:
            on_progress(msg)

    @client.event
    async def on_ready():
        try:
            guild = client.guilds[0]
            _progress(f"서버 연결: {guild.name}")

            from src.core.profile import get_user_id, get_user_name

            # 에이전트 매핑
            agents = {a["id"]: a for a in db.list_agents()}
            user_id = get_user_id()
            user_name = get_user_name()

            # 아바타 로드
            from src.bot.core import _get_avatar_bytes

            # glimi 채널 매핑
            discord_channels = {}
            for cat in guild.categories:
                if cat.name.startswith("glimi"):
                    for ch in cat.text_channels:
                        discord_channels[ch.name] = ch

            # DB 채널별 메시지
            overview = db.get_channel_overview()
            _progress(f"복원 대상: {len(overview)}개 채널")

            for ch_info in overview:
                ch_name = ch_info["channel"]
                dc_ch = discord_channels.get(ch_name)
                if not dc_ch:
                    _progress(f"  {ch_name}: Discord 채널 없음 (스킵)")
                    continue

                # Discord에 이미 메시지가 있으면 스킵
                has_msgs = False
                async for _ in dc_ch.history(limit=1):
                    has_msgs = True
                    break
                if has_msgs:
                    _progress(f"  {ch_name}: 이미 메시지 있음 (스킵)")
                    continue

                # DB에서 전체 메시지 (시간순)
                conn = db.get_conn()
                messages = [dict(r) for r in conn.execute(
                    "SELECT * FROM conversations WHERE channel=? ORDER BY timestamp ASC",
                    (ch_name,)
                ).fetchall()]
                conn.close()

                if not messages:
                    continue

                _progress(f"  {ch_name}: {len(messages)}건 복원 중...")

                # Webhook 캐시
                webhooks = {}
                sent = 0

                for msg in messages:
                    speaker_id = msg["speaker"]
                    content = msg["message"]
                    ts = msg.get("timestamp", "")[:16]

                    if speaker_id == user_id:
                        # 오너 메시지
                        display_name = user_name
                        avatar = None
                    elif speaker_id in agents:
                        agent = agents[speaker_id]
                        display_name = agent["name"]
                        avatar = _get_avatar_bytes(speaker_id)
                    else:
                        display_name = speaker_id
                        avatar = None

                    # Webhook 가져오기/생성
                    wh_key = display_name
                    if wh_key not in webhooks:
                        wh_name = f"glimi-restore-{wh_key}"
                        # 기존 webhook 찾기
                        existing = await dc_ch.webhooks()
                        wh = None
                        for w in existing:
                            if w.name == wh_name:
                                wh = w
                                break
                        if not wh:
                            wh = await dc_ch.create_webhook(name=wh_name, avatar=avatar)
                        webhooks[wh_key] = wh

                    wh = webhooks[wh_key]

                    try:
                        await wh.send(content=content, username=display_name)
                        sent += 1

                        # rate limit 방지
                        if sent % 5 == 0:
                            await asyncio.sleep(1)
                        else:
                            await asyncio.sleep(0.3)

                    except Exception as e:
                        result["errors"].append(f"{ch_name} #{msg.get('id', '?')}: {e}")
                        await asyncio.sleep(2)  # rate limit 대기

                    if sent % 20 == 0:
                        _progress(f"  {ch_name}: {sent}/{len(messages)}건 전송")

                # 복원용 webhook 정리
                for wh in webhooks.values():
                    try:
                        await wh.delete()
                    except Exception:
                        pass

                result["restored"] += sent
                result["channels"] += 1
                _progress(f"  {ch_name}: {sent}건 완료")

            result["ok"] = True
            _progress(f"복원 완료 — {result['channels']}개 채널, {result['restored']}건 메시지")

        except Exception as e:
            result["error"] = str(e)
            result["errors"].append(traceback.format_exc())
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=600)  # 10분
    except (asyncio.CancelledError, asyncio.TimeoutError):
        if not result["ok"]:
            result["error"] = "시간 초과"
    except Exception as e:
        if not result["ok"]:
            result["error"] = str(e)

    return result


def run_restore(on_progress: Optional[Callable[[str], None]] = None) -> dict:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(restore_messages(on_progress))
    finally:
        loop.close()
