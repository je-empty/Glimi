"""App shim for the Glimi-kernel runtime module.

The agent runtime now lives in ``glimi.runtime`` (kernel, storage/profile/
observer-neutral). This shim wires the Community app's adapters into the kernel,
ensures the memory module is wired too, and re-exports the public API so
existing ``from src.core.runtime import runtime`` call sites keep working.
"""
from glimi.runtime import *  # noqa: F401,F403  (re-export kernel runtime API)
from glimi.runtime import (  # noqa: F401  (explicit — community/budget seam)
    set_active_community,
    community_id,
    get_store,
)
from glimi import runtime as _kr
from src.adapters.kernel_store import (
    kernel_store as _kernel_store,
    profile_provider as _profile_provider,
    owner_context as _owner_context,
    observer as _observer_impl,
)

# 앱 어댑터 주입 (kernel runtime 의 module-global _store 등을 채움)
_kr.set_store(_kernel_store)
_kr.set_profiles(_profile_provider)
_kr.set_owner(_owner_context)
_kr.set_observer(_observer_impl)

# LLM 사용량 회계 sink 주입 — facade(glimi.llm.generate) Path B 가 실측 토큰/비용을
# usage_records 에 적립. 미등록이면 no-op (standalone). 같은 store 사용.
try:
    from glimi import llm as _kllm
    _kllm.set_usage_sink(_kernel_store)
except Exception:
    pass

# memory 도 같이 주입 보장 (runtime → memory 호출 경로)
import src.core.memory  # noqa: F401,E402


# ── 앱-특화 훅 (커널에서 콜백으로 외부화한 것) ──────────────────────

def _app_leak_reporter(agent_id: str, channel_name: str, leaked_text: str, source: str):
    """leak 감지 → dev_requests 큐 자동 적재 (self-healing 안전망). dedup 60min."""
    from src.core.dev_agent import enqueue_dev_request, find_similar_recent_request
    from src import community as _community
    community_id = _community.get_community_id() or "unknown"
    payload = {
        "channel": channel_name or "(unknown)",
        "severity": "low",
        "repro": (
            f"agent={agent_id} 가 채팅에 reasoning/status 텍스트를 그대로 출력. "
            f"감지된 leak (앞 200자): {leaked_text[:200]!r}. 소스: {source}."
        ),
        "expected": "정상 채팅 발화. 메타·정리·계획 텍스트는 절대 채널에 안 보여야 함.",
        "actual": "채팅 라인에 메타 출력. (drop 됨, 사용자엔 미노출)",
        "notes": "auto-filed by runtime leak hook. 패턴 추가나 prompt 수정 필요할 수 있음.",
    }
    if find_similar_recent_request(community_id, payload, window_minutes=60):
        return
    enqueue_dev_request(community_id, agent_id or "system", payload)


def _app_profile_reminder(owner_profile: dict):
    """오너 프로필 이상치 → 정정 요청 힌트 텍스트 (없으면 None)."""
    from src.core.profile_anomalies import check_user_profile_anomalies, format_anomaly_hint
    return format_anomaly_hint(check_user_profile_anomalies(owner_profile or {}))


_kr.set_leak_reporter(_app_leak_reporter)
_kr.set_profile_reminder_fn(_app_profile_reminder)

# 재export 가 빠뜨리는 인스턴스/상수 명시 보강
runtime = _kr.runtime  # noqa: F811
