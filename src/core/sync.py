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


def normalize_channel_name(name: str) -> str:
    """채널명 정규화 — 공백 → dash, 양 끝 trim. Discord 가 자동 변환하는 것과 일치시켜
    DB·runtime cache 와 어긋나는 회귀 방지."""
    import re as _re
    if not name:
        return name
    return _re.sub(r"\s+", "-", name.strip())


async def ensure_unique_channel(guild, ch_name: str, category=None, **kwargs) -> tuple:
    """채널 보장 함수 — 같은 이름 채널 있으면 재사용, 없으면 생성. **중복 생성 절대 방지**.

    회귀: 여러 sync/mgr/scene path 가 각자 create_text_channel 호출 → 같은 이름 다중 생성.
    이 helper 통과하면 always at-most-1. 모든 채널 생성 callers 가 이 함수 거쳐야 함.

    kwargs 는 create_text_channel 의 추가 인자 (overwrites 등) 통과.

    Returns: (channel, created: bool)
    """
    normalized = normalize_channel_name(ch_name)
    # 1) 정규화된 이름으로 존재 확인 (Discord 측 정규화도 포함)
    existing = discord_lib.utils.get(guild.text_channels, name=normalized)
    if existing:
        return existing, False
    # 2) 원본 이름 (공백 포함) 도 확인 — Discord 가 자동변환 안 했을 가능성
    if normalized != ch_name:
        existing = discord_lib.utils.get(guild.text_channels, name=ch_name)
        if existing:
            return existing, False
    # 3) 신규 생성 (정규화된 이름으로)
    new_ch = await guild.create_text_channel(normalized, category=category, **kwargs)
    return new_ch, True


# 후방호환 alias — 기존 sync.py 내부 caller (이미 옮겨짐)
_ensure_unique_channel = ensure_unique_channel
_normalize_ch_name = normalize_channel_name


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


def _build_name_order_map() -> dict[str, int]:
    """에이전트 이름 → DB 등록 순번. 채널명 파싱해서 정렬 키 얻는 용도.
    persona → mgr → creator 순으로 번호 매김 (creation order 의 근사)."""
    try:
        agents = db.list_agents()
    except Exception:
        return {}
    order: dict[str, int] = {}
    # type 우선순위: persona 먼저, mgr, creator 마지막
    type_prio = {"persona": 0, "mgr": 1, "creator": 2}
    sorted_agents = sorted(agents, key=lambda a: (type_prio.get(a["type"], 99), a["id"]))
    for idx, a in enumerate(sorted_agents):
        order[a["name"]] = idx
    return order


def _channel_sort_key(ch_name: str, name_order: dict[str, int]) -> tuple:
    """채널 내부 정렬 키.
    규칙:
      - glimi-mgr: mgr-system-log → mgr-dashboard → mgr-creator
      - glimi-dm: 에이전트 creation order (name_order)
      - glimi-group: 채널명 알파벳
      - glimi-internal-dm: 두 참여자의 order (min, max)
      - glimi-internal-group: 채널명 알파벳
    """
    MGR_ORDER = ["mgr-system-log", "mgr-dashboard", "mgr-creator"]
    BIG = 10_000  # unknown 이름은 맨 뒤
    if ch_name in MGR_ORDER:
        return (0, MGR_ORDER.index(ch_name))
    if ch_name.startswith("dm-"):
        name = ch_name[len("dm-"):]
        return (0, name_order.get(name, BIG), name)
    if ch_name.startswith("internal-dm-"):
        rest = ch_name[len("internal-dm-"):]
        # "A-B" 형태. 이름에 "-" 가 포함되지 않는다고 가정 (한글 이름).
        parts = rest.split("-", 1)
        if len(parts) == 2:
            a, b = parts
            oa = name_order.get(a, BIG)
            ob = name_order.get(b, BIG)
            return (0, min(oa, ob), max(oa, ob), rest)
        return (0, BIG, rest)
    if ch_name.startswith("internal-group-") or ch_name.startswith("group-"):
        return (0, ch_name)
    # 기타 (예: glimi-* 아닌 것) → 맨 뒤
    return (1, ch_name)


def _get_token() -> Optional[str]:
    env_path = community.get_community_dir() / ".env"
    if not env_path.exists():
        return None
    # encoding="utf-8" 명시 — Windows 기본 codepage (cp949) 가 .env 안 UTF-8 한글
    # 주석 못 읽는 회귀 fix. errors="replace" 로 손상된 바이트도 무시.
    with open(env_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                return val if val and val != "여기에_봇_토큰" else None
    return None


def _get_expected_channels() -> set[str]:
    """DB channels 테이블이 단일 진실원.

    봇/튜토리얼이 채널을 실제로 만들 때마다 channels 테이블에 등록됨.
    sync 는 '테이블에 있는 것을 Discord 에 반영' 할 뿐 — 채널 종류나
    에이전트 타입으로 유추해서 미리 만들지 않음.

    초기 커뮤니티 상태: mgr-dashboard 만 (튜토리얼 greet 단계).
    튜토리얼 진행되면 phase 별로 mgr-creator, mgr-system-log, dm-* 가 추가 등록.
    """
    channels = set()
    for ch in db.get_channel_overview():
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
    dry_run: bool = False,
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
            # channels_filter 가 있으면 (가동 복구 케이스) 전체 채널 재구조화는 스킵 —
            # 유저는 특정 채널의 메시지 drift 만 고치고 싶어함. 불필요한 delete/move/reorder 제거.
            expected = _get_expected_channels()
            fast_path = bool(channels_filter)
            surviving = {}

            if fast_path:
                _progress(f"빠른 경로 — {len(channels_filter)}개 채널만 메시지 복구")
                # 필터 대상 채널만 surviving 에 등록. 없으면 생성 (구조 reorg 없이).
                for ch_name in channels_filter:
                    existing = discord_lib.utils.get(guild.text_channels, name=ch_name)
                    if existing:
                        surviving[ch_name] = existing
                    else:
                        # 누락 — 카테고리만 확보 후 채널 생성
                        cat_name = _get_category_for_channel(ch_name)
                        cat = discord_lib.utils.get(guild.categories, name=cat_name)
                        if not cat:
                            try:
                                cat = await guild.create_category(cat_name)
                            except Exception as e:
                                result["errors"].append(f"카테고리 생성 실패 ({cat_name}): {e}")
                                continue
                        try:
                            new_ch, created = await _ensure_unique_channel(guild, ch_name, cat)
                            surviving[ch_name] = new_ch
                            if created:
                                result["channels_created"].append(ch_name)
                                _progress(f"  생성: {ch_name}")
                            else:
                                _progress(f"  유지: {ch_name} (이미 존재)")
                        except Exception as e:
                            result["errors"].append(f"생성 실패 ({ch_name}): {e}")
            else:
                _progress("채널 정리 중...")
                glimi_categories = [c for c in guild.categories if c.name.startswith("glimi")]
                all_glimi_channels = []
                for cat in glimi_categories:
                    for ch in cat.text_channels:
                        all_glimi_channels.append(ch)

                for ch in all_glimi_channels:
                    correct_cat = _get_category_for_channel(ch.name)
                    if ch.name not in expected:
                        if dry_run:
                            result["channels_deleted"].append(ch.name)
                            _progress(f"  [dry-run] 삭제 예정: {ch.name}")
                        else:
                            try:
                                await ch.delete(reason="Glimi Sync: 불필요")
                                result["channels_deleted"].append(ch.name)
                                _progress(f"  삭제: {ch.name}")
                            except Exception as e:
                                result["errors"].append(f"삭제 실패 ({ch.name}): {e}")
                    elif ch.category and ch.category.name != correct_cat:
                        if dry_run:
                            surviving[ch.name] = ch
                            _progress(f"  [dry-run] 이동 예정: {ch.name} → {correct_cat}")
                        else:
                            try:
                                target_cat = discord_lib.utils.get(guild.categories, name=correct_cat)
                                if not target_cat:
                                    target_cat = await guild.create_category(correct_cat)
                                await ch.edit(category=target_cat)
                                surviving[ch.name] = ch
                                _progress(f"  이동: {ch.name} → {correct_cat}")
                            except Exception as e:
                                result["errors"].append(f"이동 실패 ({ch.name}): {e}")
                                surviving[ch.name] = ch
                    elif ch.name not in surviving:
                        surviving[ch.name] = ch
                    else:
                        if not dry_run:
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
                    if dry_run:
                        _progress(f"  [dry-run] 카테고리 생성 예정: {cat_name}")
                    else:
                        cat = await guild.create_category(cat_name)
                        _progress(f"  카테고리 생성: {cat_name}")

                # mgr 카테고리는 expected 중에서 MGR_ORDER 순으로
                if cat_name == "glimi-mgr":
                    needed = [ch for ch in MGR_ORDER if ch in expected and ch not in surviving]

                for ch_name in needed:
                    if dry_run:
                        result["channels_created"].append(ch_name)
                        _progress(f"  [dry-run] 생성 예정: {ch_name}")
                        continue
                    try:
                        new_ch, created = await _ensure_unique_channel(guild, ch_name, cat)
                        surviving[ch_name] = new_ch
                        if created:
                            result["channels_created"].append(ch_name)
                            _progress(f"  생성: {ch_name}")
                        else:
                            _progress(f"  유지: {ch_name} (이미 존재)")
                    except Exception as e:
                        result["errors"].append(f"생성 실패 ({ch_name}): {e}")

            # 카테고리별 채널 정렬 — mgr 고정 순서 + dm 은 agent creation order + group/internal 알파벳.
            # dry_run 에서도 실행: position 이동은 DB 영향 없고 Discord UI 상 정리만 영향.
            _progress("카테고리 내부 채널 정렬 중...")
            name_order = _build_name_order_map()
            for cat in guild.categories:
                if not cat.name.startswith("glimi"):
                    continue
                # 현재 이 카테고리의 채널들 (surviving 포함 + 방금 만들어진 것)
                in_cat = [c for c in cat.text_channels]
                # 정렬 키로 sort
                in_cat.sort(key=lambda c: _channel_sort_key(c.name, name_order))
                for i, ch in enumerate(in_cat):
                    if ch.position == i:
                        continue
                    try:
                        await ch.edit(position=i)
                        await asyncio.sleep(0.2)
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
            from src.bot.core import _get_profile_image_bytes

            # 메시지 sync 제외 채널 — 채널 존재는 보장하지만 DB↔Discord 메시지 카운트 맞춤 X.
            # mgr-system-log 는 런타임 로그가 webhook 으로 실시간 누적되는 곳이라 매번 drift.
            MSG_SYNC_EXCLUDED = {"mgr-system-log"}

            for ch_name in list(surviving.keys()):
                ch = surviving[ch_name]
                # 채널 필터 적용
                if channels_filter and ch_name not in channels_filter:
                    continue
                # mgr-system-log 같은 런타임 로그 채널은 메시지 sync 스킵 (존재만 보장)
                if ch_name in MSG_SYNC_EXCLUDED:
                    _progress(f"  {ch_name}: 메시지 sync 스킵 (로그 채널)")
                    result["channels_scanned"] += 1
                    continue

                # DB 메시지 timestamp 순 전체 로드 (divergence 스캔 용)
                conn = db.get_conn()
                db_messages_ordered = [dict(r) for r in conn.execute(
                    "SELECT * FROM conversations WHERE channel=? ORDER BY timestamp ASC, id ASC",
                    (ch_name,)
                ).fetchall()]
                conn.close()
                db_count = len(db_messages_ordered)

                # Discord 메시지 oldest_first 전체 로드
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

                # ── 순서 기반 divergence 찾기 (다층 lookahead) ──
                # 회귀 1: strict positional walk → 1건 차이가 후속 전체 캐스케이드 mismatch 로 판정.
                # 회귀 2: persona 응답이 Discord 에선 N개로 split 발송, DB 에는 합쳐서 1 row 저장된
                #         경우 (구버전 logging 잔재) — 텍스트 동등 비교만 하면 1↔N 매칭 못함.
                # 다층 매칭 순서:
                #   (a) 정확 일치 — 가장 흔한 경로
                #   (b) DB-1개 ↔ Discord-N개: db[i] == discord[j..j+M] 의 join (sep 다양)
                #   (c) Discord-1개 ↔ DB-N개 (역방향): discord[j] == db[i..i+M] 의 join
                #   (d) Discord-only (외부 발화): db[i] 가 discord[j+1..j+L] 어딘가에 그대로 등장
                #   (e) 위 모두 실패 → 진짜 divergence, walk 종료
                LOOKAHEAD = 5
                JOIN_SEPS = ("\n", " ", "\n\n", "")
                discord_skip_idxs: list[int] = []  # Discord-only → 삭제 후보
                db_skip_idxs: list[int] = []       # DB-only → Discord 로 send 후보 (중간 누락)
                i = 0  # db cursor
                j = 0  # discord cursor

                def _try_join_match(target: str, source_msgs, start: int, max_count: int,
                                    text_fn) -> int:
                    """source_msgs[start..start+k] 까지 join 했을 때 target 과 같아지는 k 반환.
                    못 찾으면 -1."""
                    for k in range(1, max_count + 1):
                        if start + k > len(source_msgs):
                            break
                        parts = [text_fn(source_msgs[start + m]) for m in range(k + 1)]
                        for sep in JOIN_SEPS:
                            if sep.join(parts) == target:
                                return k
                    return -1

                _db_text = lambda r: (r.get("message") if isinstance(r, dict) else "") or ""
                _dc_text = lambda m: (m.content or "")

                while i < db_count and j < discord_count:
                    db_text = _db_text(db_messages_ordered[i])
                    dc_text = _dc_text(discord_msgs[j])
                    # (a) 정확 일치
                    if db_text == dc_text:
                        i += 1
                        j += 1
                        continue
                    # (b) DB 1 ↔ Discord N 매칭
                    consume_dc = _try_join_match(db_text, discord_msgs, j,
                                                  min(LOOKAHEAD, discord_count - j - 1),
                                                  _dc_text)
                    if consume_dc > 0:
                        # discord[j..j+consume_dc] (총 consume_dc+1 개) 가 db[i] 1개에 대응.
                        # 양쪽 다 일치하니 추가 액션 없음.
                        i += 1
                        j += consume_dc + 1
                        continue
                    # (c) Discord 1 ↔ DB N 매칭
                    consume_db = _try_join_match(dc_text, db_messages_ordered, i,
                                                  min(LOOKAHEAD, db_count - i - 1),
                                                  _db_text)
                    if consume_db > 0:
                        i += consume_db + 1
                        j += 1
                        continue
                    # (d) Discord-only — db[i] 가 discord[j+1..end] 어디든 정확히 있는지 풀스캔.
                    # LOOKAHEAD 안에서만 찾으면 큰 갭 (e.g., 70+ 건 누락) 을 못 다리 놓음.
                    # 대신 가장 가까운 매치 우선 — "skip 거리" 최소화 위해 첫 매치만 사용.
                    found = -1
                    for k in range(j + 1, discord_count):
                        if _dc_text(discord_msgs[k]) == db_text:
                            found = k
                            break
                    if found != -1:
                        discord_skip_idxs.extend(range(j, found))
                        j = found + 1
                        i += 1
                        continue
                    # (e) DB-only — discord[j] 가 db[i+1..end] 어디든 정확히 있는지 풀스캔.
                    found = -1
                    for k in range(i + 1, db_count):
                        if _db_text(db_messages_ordered[k]) == dc_text:
                            found = k
                            break
                    if found != -1:
                        db_skip_idxs.extend(range(i, found))
                        i = found + 1
                        j += 1
                        continue
                    # 진짜 divergence — 양방향 모두 매치 못 함. db[i] / discord[j] 둘 다 unique.
                    # 하나씩만 카운팅 (db[i] = DB-only, discord[j] = Discord-only) 하고 진행.
                    # 끝까지 못 만나면 break 인 게 맞지만, 단발성 mismatch 는 양쪽 unique 처리 후 진행.
                    db_skip_idxs.append(i)
                    discord_skip_idxs.append(j)
                    i += 1
                    j += 1

                divergence = i
                # discord_to_delete: 중간 Discord-only 들 + 진짜 divergence 이후 Discord 잔여
                discord_to_delete = [discord_msgs[k] for k in discord_skip_idxs]
                discord_to_delete += discord_msgs[j:]
                # db_to_send: 중간 DB-only 들 + 진짜 divergence 이후 DB 잔여
                db_to_send = [db_messages_ordered[k] for k in db_skip_idxs]
                db_to_send += db_messages_ordered[i:]

                if not discord_to_delete and not db_to_send:
                    result["channels_scanned"] += 1
                    await asyncio.sleep(0.3)
                    continue

                # ── 안전 brake — 작은 divergence 가 대량 삭제로 비대화하는 경우 abort ──
                # 회귀: 채팅 사이에 Discord-only 메시지 (수동 삽입/삭제) 1건 있으면 그 지점부터
                # 끝까지 모든 메시지가 mismatch 로 판정 → 수십~수백건 일괄 삭제. Discord rate-limit
                # 걸려서 force-kill 시 대화 손실. 보수적 임계: divergence 가 일찍 (<10) 이면서
                # 삭제 대상이 50건 초과면 sync 중단 + 경고.
                LARGE_DELETE_THRESHOLD = 50
                EARLY_DIVERGENCE = 10
                if (len(discord_to_delete) > LARGE_DELETE_THRESHOLD
                        and divergence < EARLY_DIVERGENCE):
                    msg = (f"  {ch_name}: divergence={divergence} 인데 삭제 {len(discord_to_delete)}건 — "
                           f"안전 brake 발동, sync 중단. 수동 점검 필요.")
                    _progress(msg)
                    result["errors"].append(
                        f"{ch_name}: 안전 brake (divergence={divergence}, "
                        f"to_delete={len(discord_to_delete)})"
                    )
                    result["channels_scanned"] += 1
                    await asyncio.sleep(0.3)
                    continue

                # 재생성은 DB 가 완전히 비어있을 때만 (discord 쪽 대량 삭제 개별로 하느니 채널 만드는게 빠름).
                # 그 외엔 항상 in-place: divergence 부터 Discord 개별 삭제 + DB 앞에서부터 재전송.
                # 이전엔 discord_to_delete > 20 이면 재생성했는데, 중간 갭 하나 때문에 채널 통째로
                # 채널 재생성 path 제거 (사용자 요청). DB 가 비어있다고 채널 통째 삭제·재생성 하면
                # 채널 ID 변경 + pin/webhook/permission 모두 날아감 — 너무 침습적.
                # 항상 in-place: 메시지만 개별 삭제 + DB→Discord 재전송.
                # divergence 부터 Discord 메시지 개별 삭제 (oldest→newest 순)
                if discord_to_delete:
                    _progress(
                        f"  {ch_name}: divergence={divergence}, Discord {len(discord_to_delete)}건 개별 삭제"
                    )
                    deleted = 0
                    for idx, msg in enumerate(discord_to_delete):
                        try:
                            await msg.delete()
                            deleted += 1
                            await asyncio.sleep(0.5)
                            if deleted % 20 == 0:
                                _progress(f"  {ch_name}: {deleted}/{len(discord_to_delete)}건 삭제")
                        except Exception:
                            pass
                    if deleted:
                        total_discord_to_db += deleted
                        _progress(f"  {ch_name}: Discord 메시지 {deleted}건 삭제 완료")

                # ── DB → Discord: divergence 부터 순서대로 webhook 전송 ──
                if db_to_send:
                    _progress(f"  {ch_name}: DB→Discord {len(db_to_send)}건 순서대로 전송...")
                    webhooks = {}
                    sent = 0
                    for msg in db_to_send:
                        speaker_id = msg["speaker"]
                        content = msg["message"]

                        if speaker_id == user_id:
                            display_name = user_name
                            avatar = None
                        elif speaker_id in agents_by_id:
                            display_name = agents_by_id[speaker_id]["name"]
                            avatar = _get_profile_image_bytes(speaker_id)
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
                                _progress(f"  {ch_name}: {sent}/{len(db_to_send)}건")
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
                    _progress(f"  {ch_name}: DB→Discord {sent}건 전송 완료")

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
    dry_run: bool = False,
) -> dict:
    """Discord·DB 싱크. dry_run=True 면 Discord 변경 없이 diff 만 반환 (Scan 버튼용)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sync_community(on_progress, channels_filter, dry_run=dry_run))
    finally:
        loop.close()


async def scan_community(
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """Discord 채널별 메시지 카운트만 집계 (content fetch 안 함).
    Scan 버튼 전용 — 빠른 read-only diff. DB·Discord 변경 없음.
    반환: {"ok": bool, "counts": {ch_name: int}, "total": int, "channels_scanned": int, "error": optional}
    """
    token = _get_token()
    if not token:
        return {"ok": False, "error": "토큰 미설정", "counts": {}, "total": 0, "channels_scanned": 0}

    def _progress(msg: str):
        log_writer.system(f"[Scan] {msg}")
        if on_progress:
            on_progress(msg)

    counts: dict[str, int] = {}
    discord_channels: list[dict] = []
    discord_categories: list[str] = []
    orphan_outside: list[dict] = []  # glimi-* 카테고리 밖에 있는 mgr-/dm-/group-/internal- 패턴 채널
    result = {
        "ok": False,
        "counts": counts,
        "discord_channels": discord_channels,
        "discord_categories": discord_categories,
        "orphan_outside": orphan_outside,
        "total": 0,
        "channels_scanned": 0,
        "error": None,
    }

    intents = discord_lib.Intents.default()
    intents.guilds = True
    intents.message_content = True
    client = discord_lib.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            if not client.guilds:
                result["error"] = "서버 없음"
                await client.close()
                return
            guild = client.guilds[0]
            _progress(f"서버 연결: {guild.name}")

            glimi_cats = [c for c in guild.categories if c.name.startswith("glimi")]
            for c in glimi_cats:
                discord_categories.append(c.name)
            total_channels = sum(len(c.text_channels) for c in glimi_cats)
            _progress(f"스캔 대상: {total_channels}개 채널 · 카테고리 {len(glimi_cats)}개")

            scanned = 0
            for cat in glimi_cats:
                for ch in cat.text_channels:
                    cnt = 0
                    try:
                        async for _ in ch.history(limit=None):
                            cnt += 1
                    except discord_lib.Forbidden:
                        _progress(f"  {ch.name}: 권한 없음 (스킵)")
                        discord_channels.append({
                            "name": ch.name, "category": cat.name,
                            "msg_count": None, "error": "forbidden",
                        })
                        continue
                    except Exception as e:
                        _progress(f"  {ch.name}: 실패 ({e})")
                        discord_channels.append({
                            "name": ch.name, "category": cat.name,
                            "msg_count": None, "error": str(e),
                        })
                        continue
                    counts[ch.name] = cnt
                    discord_channels.append({
                        "name": ch.name, "category": cat.name, "msg_count": cnt,
                    })
                    scanned += 1
                    _progress(f"  {ch.name} [{cat.name}]: {cnt}건 ({scanned}/{total_channels})")

            # orphan 채널 — glimi-* 카테고리 밖에 있는 패턴 매칭 채널 (mgr-/dm-/group-/internal-)
            orphan_patterns = ("mgr-", "dm-", "group-", "internal-")
            for ch in guild.text_channels:
                if not isinstance(ch, discord_lib.TextChannel):
                    continue
                if ch.category and ch.category.name.startswith("glimi"):
                    continue
                if not any(ch.name.startswith(p) for p in orphan_patterns):
                    continue
                cat_name = ch.category.name if ch.category else "(no category)"
                orphan_outside.append({"name": ch.name, "category": cat_name})
                _progress(f"  ⚠ orphan: #{ch.name} [{cat_name}] (glimi 카테고리 밖)")

            result["channels_scanned"] = scanned
            result["total"] = sum(counts.values())
            result["ok"] = True
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=180)
    except asyncio.TimeoutError:
        result["error"] = "스캔 타임아웃 (180s)"
    except Exception as e:
        result["error"] = str(e)
        _sync_error_log(f"[Scan] 크래시: {e}\n{traceback.format_exc()}")

    _progress(f"스캔 완료: 총 {result['total']}건 · {result['channels_scanned']}개 채널")
    return result


def run_scan(on_progress: Optional[Callable[[str], None]] = None) -> dict:
    """scan_community 동기 래퍼 — TUI·web 공통."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scan_community(on_progress))
    finally:
        loop.close()


async def arrange_with_guild(guild, on_progress: Optional[Callable[[str], None]] = None) -> dict:
    """이미 연결된 Discord guild 를 받아 카테고리·채널 순서 정렬 (토큰 재연결 X).
    봇 on_ready 에서 이 함수를 직접 호출해 즉시 정렬 가능."""
    def _progress(msg: str):
        log_writer.system(f"[Arrange] {msg}")
        if on_progress:
            on_progress(msg)

    result = {"ok": False, "moved": 0, "categories_reordered": 0, "channels_reordered": 0, "error": None}

    try:
        # 1) 카테고리 순서
        existing_cats = {c.name: c for c in guild.categories}
        for i, cat_name in enumerate(CATEGORY_ORDER):
            cat = existing_cats.get(cat_name)
            if cat and cat.position != i:
                try:
                    await cat.edit(position=i)
                    result["categories_reordered"] += 1
                    await asyncio.sleep(0.2)
                except Exception as e:
                    _progress(f"  카테고리 이동 실패 ({cat_name}): {e}")

        # 2) 카테고리별 채널 정렬
        name_order = _build_name_order_map()
        for cat in guild.categories:
            if not cat.name.startswith("glimi"):
                continue
            in_cat = list(cat.text_channels)
            in_cat.sort(key=lambda c: _channel_sort_key(c.name, name_order))
            for i, ch in enumerate(in_cat):
                if ch.position == i:
                    continue
                try:
                    await ch.edit(position=i)
                    result["channels_reordered"] += 1
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
            if in_cat:
                _progress(f"  {cat.name}: {len(in_cat)}개 채널")

        result["moved"] = result["categories_reordered"] + result["channels_reordered"]
        result["ok"] = True
        _progress(f"완료 — 카테고리 {result['categories_reordered']}개, 채널 {result['channels_reordered']}개 이동")
    except Exception as e:
        result["error"] = str(e)
        _sync_error_log(f"[Arrange] 크래시: {e}\n{traceback.format_exc()}")

    return result


async def arrange_community(on_progress: Optional[Callable[[str], None]] = None) -> dict:
    """봇이 꺼진 상태에서 대시보드가 직접 호출하는 경로 — 자체 Discord client 사용."""
    token = _get_token()
    if not token:
        return {"ok": False, "error": "토큰 미설정", "moved": 0}

    result = {"ok": False, "moved": 0, "categories_reordered": 0, "channels_reordered": 0, "error": None}

    intents = discord_lib.Intents.default()
    intents.guilds = True
    client = discord_lib.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            if not client.guilds:
                result["error"] = "서버 없음"
                await client.close()
                return
            guild = client.guilds[0]
            r = await arrange_with_guild(guild, on_progress)
            result.update(r)
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=60)
    except asyncio.TimeoutError:
        result["error"] = "타임아웃 (60s)"
    except Exception as e:
        result["error"] = str(e)

    return result


def run_arrange(on_progress: Optional[Callable[[str], None]] = None) -> dict:
    """arrange_community 동기 래퍼."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(arrange_community(on_progress))
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
            from src.bot.core import _get_profile_image_bytes

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
                        avatar = _get_profile_image_bytes(speaker_id)
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
