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

from src import community

# ── 환경변수 (커뮤니티별 .env) ────────────────────────

community.ensure_dirs()
load_dotenv(community.get_env_path())

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
MGR_ID = "agent-mgr-001"

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

# ── 개발 요청 상태 ───────────────────────────────────

DEV_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dev")
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
