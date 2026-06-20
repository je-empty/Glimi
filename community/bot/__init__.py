"""
Project Glimi — Bot 공유 상태 및 인스턴스

모든 bot 하위 모듈이 공유하는 상태, 상수, bot 인스턴스.
"""
import os
import logging
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

from community import community

# ── 환경변수 (커뮤니티별 .env) ────────────────────────

community.ensure_dirs()

# 부모 프로세스 env 가 섞여들어 stale 값이 남는 회귀 fix:
# 커뮤니티 .env 에 명시되지 않은 DISCORD_* 키는 부모에서 상속받지 않도록 미리 unset.
# (예: 새 community 의 .env 에 DISCORD_GUILD_ID 가 없으면 → 부모 프로세스의 GUILD_ID
# (다른 community 거) 가 그대로 살아 봇이 엉뚱한 guild 로 시도하던 회귀)
_env_path = community.get_env_path()
try:
    if os.path.exists(_env_path):
        with open(_env_path, "r", encoding="utf-8") as _ef:
            _file_keys = {
                ln.split("=", 1)[0].strip()
                for ln in _ef
                if ln.strip() and not ln.strip().startswith("#") and "=" in ln
            }
        for _k in ("DISCORD_GUILD_ID", "DISCORD_OWNER_ID"):
            if _k not in _file_keys and _k in os.environ:
                os.environ.pop(_k, None)
except Exception:
    pass

# override=True — 커뮤니티 .env 가 프로세스에 이미 있는 env 변수보다 우선.
load_dotenv(_env_path, override=True)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OWNER_DISCORD_ID = os.getenv("DISCORD_OWNER_ID")

# ── 로깅 ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="\033[90m%(asctime)s\033[0m │ %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)
log = logging.getLogger("glimi")

# ── Bot 인스턴스 ──────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, heartbeat_timeout=120)

# ── 채널 상수 ─────────────────────────────────────────

MGR_CHANNEL = "mgr-dashboard"
MGR_SYSTEM_LOG = "mgr-system-log"
CREATOR_CHANNEL = "mgr-creator"
DEV_CHANNEL = "mgr-dev-request"  # dev manager (세나) triage channel — request_dev_fix 결과 보고
MGR_ID = "agent-mgr-001"
CREATOR_ID = "agent-creator-001"
DEV_ID = "agent-dev-001"


# ── internal-dm 채널명 정렬 컨벤션 ────────────────────────────
# Yuna (mgr) 참여 시 항상 먼저, 다음 Hana (creator), 그 외는 입력 순서 유지.
# 일관성 위해 모든 internal-dm 생성 경로가 이 helper 를 거쳐야 함.
# (이전엔 호출 사이트마다 f"internal-dm-{a}-{b}" 로 입력 순서에 의존 → 같은 두 에이전트가
#  두 채널명으로 나뉘는 혼란 + 유나/하나 순서 제멋대로.)

def _agent_name_priority(name: str) -> int:
    """sort 키 — 작을수록 채널명에서 앞에 온다."""
    # DB 에서 mgr/creator 이름 동적 조회도 가능하지만 순환 import 피하려고 상수.
    # 커뮤니티마다 유나/하나 이름이 다르더라도 seed_agents.json 기본값 '서유나' / '윤하나' 로 고정.
    PRIORITY = {"서유나": 0, "Yuna": 0, "윤하나": 1, "Hana": 1, "한세나": 2, "Sena": 2}
    return PRIORITY.get(name, 9)


def _norm_name_for_channel(name: str) -> str:
    """페르소나/유저 이름을 채널명 부품으로 변환.
    Discord 가 자동으로 normalize 하는 규칙과 일치:
      - 공백 → 하이픈
      - 영숫자/한글/하이픈/언더스코어 외 문자 제거
      - 연속 하이픈 → 단일
    '유키 아스나' → '유키-아스나'. DB ↔ Discord 채널명 일관성 보장.
    """
    import re as _re
    s = _re.sub(r"\s+", "-", (name or "").strip())
    s = _re.sub(r"[^\w\-가-힣ㄱ-ㅎㅏ-ㅣ]", "", s)
    s = _re.sub(r"-+", "-", s).strip("-")
    return s


def internal_dm_channel_name(a_name: str, b_name: str) -> str:
    """두 에이전트 이름으로 internal-dm 채널명 생성. 유나 우선 → 하나 → 그 외.

    페르소나 이름의 공백은 하이픈으로 normalize — Discord 자동 변환과 일치시켜
    DB/Discord 채널 이름 어긋남 방지.
    """
    if not a_name or not b_name:
        return f"internal-dm-{_norm_name_for_channel(a_name) or '?'}-{_norm_name_for_channel(b_name) or '?'}"
    pa, pb = _agent_name_priority(a_name), _agent_name_priority(b_name)
    # 우선순위 낮은(=앞) 쪽이 먼저. 동률이면 입력 순서 유지.
    first, second = (a_name, b_name) if pa <= pb else (b_name, a_name)
    return f"internal-dm-{_norm_name_for_channel(first)}-{_norm_name_for_channel(second)}"

# ── 채널 매핑 (공유 상태) ──────────────────────────────

CHANNEL_AGENT_MAP: dict[str, str] = {}      # "dm-은하윤" → "agent-persona-001"
AGENT_CHANNEL_MAP: dict[str, str] = {}      # "agent-persona-001" → "dm-은하윤"
GROUP_PARTICIPANTS: dict[str, list[str]] = {}

# ── Webhook 캐시 ─────────────────────────────────────

_webhook_cache: dict[tuple[int, str], discord.Webhook] = {}

# ── 메시지 처리 상태 ─────────────────────────────────

_processed_messages: set[int] = set()
_channel_locks: dict[str, asyncio.Lock] = {}
_agent_locks: dict[str, asyncio.Lock] = {}


def _get_channel_lock(channel_name: str) -> asyncio.Lock:
    if channel_name not in _channel_locks:
        _channel_locks[channel_name] = asyncio.Lock()
    return _channel_locks[channel_name]


def _get_agent_lock(agent_id: str) -> asyncio.Lock:
    """에이전트별 잠금 (그룹채팅 동시 전송용)"""
    if agent_id not in _agent_locks:
        _agent_locks[agent_id] = asyncio.Lock()
    return _agent_locks[agent_id]

# ── 시스템 로그 큐 ───────────────────────────────────

_system_log_queue: list[str] = []

# ── 개발 요청 상태 (커뮤니티별 — 루트 공유 금지) ───────
# 과거엔 PROJECT_ROOT/dev/pending.json 였으나, 다중 커뮤니티 subprocess 가
# 동시 기동되면 같은 파일 덮어써서 요청이 섞임. community dir 안으로 격리.

DEV_DIR = str(community.get_community_dir() / "dev")
DEV_PENDING = os.path.join(DEV_DIR, "pending.json")
DEV_RESULT = os.path.join(DEV_DIR, "result.json")
os.makedirs(DEV_DIR, exist_ok=True)

_shutdown_pending = False

# ── 유나 감시 상태 ───────────────────────────────────

_last_activity_snapshot: dict[str, int] = {}
_daily_social_count: int = 0
_daily_social_date: str = ""
DAILY_SOCIAL_LIMIT = 10
_last_log_line_count: int = 0

# ── 에러 추적 상태 ───────────────────────────────────

_runtime_error_counts: dict[str, int] = {}
_runtime_error_reported: set[str] = set()
AUTO_DEV_REQUEST_THRESHOLD = 3
