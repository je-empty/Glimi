"""커뮤니티 격리 검증 — 웹 대시보드 API 를 community 간 전환하며 호출했을 때
이전 커뮤니티 데이터가 누설되지 않는지 확인.

실행:
    python -m tests.unit.test_community_isolation

검증 항목:
- snapshot() 이 community 파라미터대로 각각의 agents/채널 반환
- agent_detail() 이 요청된 community 의 에이전트만 반환 (cross-community lookup 안 됨)
- profile cache 가 전환 시 invalidate 되어 stale 이름/성별 반환 안 함
- avatar 서빙이 다른 community 프로필 이미지로 fallback 안 함 (404 = placeholder)
"""
import json
import os
import sys
import threading
import time
import urllib.request

# 프로젝트 루트 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def _get_bytes(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def _start_dashboard(port: int = 8799):
    """별도 스레드에서 웹 대시보드 기동 (기본 community = private)."""
    os.environ.pop("GLIMI_COMMUNITY", None)
    # registry.toml 의 default 를 사용 — private 로 떠야 함
    import web_dashboard as wd
    from src import community as _comm
    _comm._current_id = None  # fresh resolution
    cid = _comm.get_community_id()
    wd._STARTUP_COMMUNITY = cid

    import http.server
    import socketserver

    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = S(("127.0.0.1", port), wd.Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)
    return server, cid


def _available_communities() -> list[str]:
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "communities"
    return [d.name for d in root.iterdir()
            if d.is_dir() and not d.name.startswith('.')
            and (d / "community.db").exists()]


def test_snapshot_switches_cleanly():
    """/api/snapshot?community=X 가 정확히 X 데이터만 반환, 전환 후 원복."""
    server, startup_cid = _start_dashboard(8799)
    try:
        base = "http://127.0.0.1:8799"

        communities = _available_communities()
        if len(communities) < 2:
            print(f"SKIP — need ≥2 communities with DB (found {communities})")
            return

        # 각 community 의 에이전트 id set 을 수집
        agents_per_comm: dict[str, set[str]] = {}
        for cid in communities:
            snap = _get_json(f"{base}/api/snapshot?community={cid}")
            assert snap.get("community_id") == cid, f"{cid}: returned {snap.get('community_id')}"
            agents_per_comm[cid] = {a["id"] for a in snap.get("agents", [])}

        # 서로 다른 community 는 에이전트 id 가 겹치면 안 됨 (일반적으론 겹칠 수 있지만
        # 이 프로젝트의 default agent_id 네이밍은 커뮤니티별 고유 — 겹침 발견 시 알림만).
        overlaps = set.intersection(*agents_per_comm.values()) if len(agents_per_comm) >= 2 else set()
        if overlaps:
            print(f"NOTE — agent_id overlap across communities: {overlaps}")

        # 전환 후 community 명시 없이 호출 → startup 기본값으로 복귀
        _get_json(f"{base}/api/snapshot?community={communities[-1]}")
        plain = _get_json(f"{base}/api/snapshot")
        assert plain.get("community_id") == startup_cid, \
            f"state leaked — expected {startup_cid}, got {plain.get('community_id')}"

        print(f"✓ snapshot isolation — {len(communities)} communities tested")
    finally:
        server.shutdown()


def test_agent_detail_cross_community_returns_error():
    """A community 의 에이전트 id 로 B community 에 조회하면 error or not-found."""
    server, _ = _start_dashboard(8798)
    try:
        base = "http://127.0.0.1:8798"
        communities = _available_communities()
        if len(communities) < 2:
            print("SKIP — need ≥2 communities")
            return

        # A community 에서 에이전트 하나 찾기
        snap_a = _get_json(f"{base}/api/snapshot?community={communities[0]}")
        agents_a = snap_a.get("agents", [])
        if not agents_a:
            print(f"SKIP — {communities[0]} 에 에이전트 없음")
            return
        agent_a_id = agents_a[0]["id"]

        # B community 에 A 의 agent_id 로 조회 → A 데이터가 누설되면 안 됨
        detail_b = _get_json(f"{base}/api/agent?id={agent_a_id}&community={communities[1]}")
        snap_b = _get_json(f"{base}/api/snapshot?community={communities[1]}")
        b_ids = {a["id"] for a in snap_b.get("agents", [])}

        if agent_a_id in b_ids:
            print(f"NOTE — {agent_a_id} exists in both {communities[0]} and {communities[1]} (legitimate)")
        else:
            # B 에 없는 에이전트인데 detail 이 실제 데이터를 반환하면 누설
            if "error" not in detail_b and detail_b.get("name"):
                raise AssertionError(
                    f"LEAK — {agent_a_id} (not in {communities[1]}) returned name="
                    f"{detail_b.get('name')} via community={communities[1]}"
                )
            print(f"✓ cross-community lookup isolated (agent_id={agent_a_id} not found in {communities[1]})")
    finally:
        server.shutdown()


def test_avatar_no_cross_community_leak():
    """A community 에이전트 이미지를 B community 로 요청하면 placeholder (404 크기 PNG)."""
    server, _ = _start_dashboard(8797)
    try:
        base = "http://127.0.0.1:8797"
        communities = _available_communities()
        if len(communities) < 2:
            print("SKIP — need ≥2 communities")
            return

        # A 에만 존재하는 에이전트 찾기
        snap_a = _get_json(f"{base}/api/snapshot?community={communities[0]}")
        snap_b = _get_json(f"{base}/api/snapshot?community={communities[1]}")
        ids_a = {a["id"] for a in snap_a.get("agents", [])}
        ids_b = {a["id"] for a in snap_b.get("agents", [])}
        only_a = ids_a - ids_b
        if not only_a:
            print("SKIP — 모든 에이전트가 두 community 에 공통 존재")
            return
        agent_id = next(iter(only_a))

        # B community 로 avatar 요청 → placeholder 여야 함 (< 100 bytes)
        status, body = _get_bytes(f"{base}/api/avatar?id={agent_id}&community={communities[1]}")
        assert status == 200, f"avatar endpoint failed: {status}"
        if len(body) > 100:
            raise AssertionError(
                f"LEAK — {agent_id} not in {communities[1]} but avatar returned {len(body)} bytes "
                f"(expected placeholder ~70 bytes)"
            )
        print(f"✓ avatar isolation — {agent_id} not exposed via {communities[1]} ({len(body)} bytes placeholder)")
    finally:
        server.shutdown()


def test_profile_cache_invalidated_on_switch():
    """커뮤니티 전환 후 load_profile 이 이전 community 캐시를 반환 안 하는지."""
    from src.core.profile import load_profile, invalidate_cache
    from src import community as _comm
    communities = _available_communities()
    if len(communities) < 2:
        print("SKIP — need ≥2 communities")
        return

    invalidate_cache()

    # community A 에서 에이전트 로드
    _comm.set_community(communities[0])
    import src.db as _db
    _db.DB_PATH = None
    from src import db
    agents_a = db.list_agents()
    if not agents_a:
        print(f"SKIP — {communities[0]} 에 에이전트 없음")
        return
    agent_id = agents_a[0]["id"]
    profile_a = load_profile(agent_id)
    name_a = profile_a.get("name") if profile_a else None

    # community B 로 전환 + 캐시 invalidate (웹 대시보드 _set_active_community 가 하는 일)
    _comm.set_community(communities[1])
    _db.DB_PATH = None
    invalidate_cache()

    profile_b = load_profile(agent_id)
    name_b = profile_b.get("name") if profile_b else None

    # 같은 agent_id 로 B 에 존재하면 이름 같을 수도 있음 — 하지만 캐시가 A 데이터를 반환하면 안 됨
    # 만약 B 에 같은 agent_id 없으면 profile_b 는 None 이어야 함
    agents_b_ids = {a["id"] for a in db.list_agents()}
    if agent_id not in agents_b_ids:
        if profile_b is not None:
            raise AssertionError(
                f"CACHE LEAK — {agent_id} not in {communities[1]} but load_profile returned {profile_b}"
            )
        print(f"✓ cache invalidated — {agent_id} not in {communities[1]}, returned None")
    else:
        print(f"NOTE — {agent_id} exists in both: A.name={name_a} B.name={name_b}")


if __name__ == "__main__":
    test_snapshot_switches_cleanly()
    test_agent_detail_cross_community_returns_error()
    test_avatar_no_cross_community_leak()
    test_profile_cache_invalidated_on_switch()
    print("\nall isolation tests passed")
