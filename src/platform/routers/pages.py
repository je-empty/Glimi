"""HTML 페이지 라우터 — 홈(커뮤니티 리스트) / 커뮤니티 상세."""
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from src.community import list_communities

from .. import accounts, templates
from ..auth import get_current_user, require_user
from ..supervisor import supervisor

from .communities import _fetch_members, _visible_communities

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    visible = _visible_communities(user)
    running = set(supervisor.list_running())
    for c in visible:
        c["running"] = c["id"] in running
        c["members"] = _fetch_members(c["id"])
        c["member_count"] = len(c["members"])

    return templates.env.TemplateResponse(
        request,
        "home.html",
        {"user": user, "communities": visible},
    )


@router.get("/community/{community_id}", response_class=HTMLResponse)
async def community_dashboard(
    request: Request,
    community_id: str,
    user: dict = Depends(require_user),
):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access to this community")

    all_ids = {c["id"] for c in list_communities()}
    if community_id not in all_ids:
        raise HTTPException(404, "community not found")

    # 구 web_dashboard 의 HTML 전체를 서빙. 별도 바 주입 대신 기존 헤더 안에 플랫폼 컨트롤 삽입.
    from .dashboard import _dash
    dashboard_html: str = _dash.HTML

    # 1) URL 중복 제거 — 대시보드 JS 가 params.get('community') 로 읽는 초기화를 직접 치환
    #    원본: `let COMMUNITY = params.get('community') || null;`
    dashboard_html = dashboard_html.replace(
        "let COMMUNITY = params.get('community') || null;",
        f'let COMMUNITY = "{community_id}";',
        1,
    )

    # 2) 헤더 안에 플랫폼 컨트롤 (Start/Stop/Restart + 홈 + 로그아웃) 주입
    platform_inject = f"""
<script>
(function() {{
  const CID = "{community_id}";
  function ready(fn) {{
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }}
  async function refresh() {{
    try {{
      const r = await fetch('/api/communities/' + CID + '/status');
      if (!r.ok) return;
      const s = await r.json();
      const badge = document.getElementById('gp-bot-status');
      const up = document.getElementById('gp-bot-uptime');
      const startBtn = document.getElementById('gp-start');
      const restartBtn = document.getElementById('gp-restart');
      const stopBtn = document.getElementById('gp-stop');
      if (!badge) return;
      if (s.running) {{
        badge.textContent = 'RUNNING';
        badge.style.background = 'var(--ok, #10b981)';
        badge.style.color = '#fff';
        if (s.uptime_sec) up.textContent = Math.round(s.uptime_sec) + 's';
        startBtn.style.display = 'none';
        restartBtn.style.display = '';
        stopBtn.style.display = '';
      }} else {{
        badge.textContent = 'STOPPED';
        badge.style.background = 'var(--text-faint, #9ca3af)';
        badge.style.color = '#fff';
        up.textContent = '';
        startBtn.style.display = '';
        restartBtn.style.display = 'none';
        stopBtn.style.display = 'none';
      }}
    }} catch (e) {{}}
  }}
  window._glimiCtrl = async function(action) {{
    try {{
      const r = await fetch('/api/communities/' + CID + '/' + action, {{ method: 'POST' }});
      if (!r.ok) {{ alert('실패: ' + await r.text()); return; }}
      setTimeout(refresh, 500);
      setTimeout(refresh, 2500);
    }} catch (e) {{ alert(e); }}
  }};
  window._glimiLogout = function() {{
    fetch('/logout', {{method:'POST'}}).then(()=>location.href='/login');
  }};
  ready(function() {{
    const hdr = document.querySelector('header.status');
    if (!hdr) return;
    // 로고를 홈 링크로 감싸기
    const brand = hdr.querySelector('.brand');
    if (brand && !brand.closest('a')) {{
      const link = document.createElement('a');
      link.href = '/';
      link.title = '플랫폼 홈';
      link.style.cssText = 'text-decoration:none;color:inherit;display:inline-flex;align-items:center;';
      brand.parentNode.insertBefore(link, brand);
      link.appendChild(brand);
      brand.removeAttribute('onclick');
      brand.style.cursor = 'pointer';
    }}
    // 기존 flex:1 spacer 앞에 서버 컨트롤 그룹 추가
    const spacer = hdr.querySelector('div[style*="flex:1"]');
    const ctrl = document.createElement('div');
    ctrl.id = 'gp-server-ctrl';
    ctrl.style.cssText = 'display:flex;align-items:center;gap:6px;margin-left:12px;';
    ctrl.innerHTML = `
      <span id="gp-bot-status" style="padding:2px 8px;border-radius:10px;background:#e5e7eb;color:#374151;font-size:10.5px;font-weight:500">…</span>
      <span id="gp-bot-uptime" style="color:var(--text-dim,#6b7280);font-size:11px;min-width:30px"></span>
      <button id="gp-start" onclick="_glimiCtrl('start')" style="background:var(--ok,#10b981);color:#fff;border:none;padding:5px 10px;border-radius:6px;cursor:pointer;font-size:12px">▶ 시작</button>
      <button id="gp-restart" onclick="_glimiCtrl('restart')" style="background:transparent;color:inherit;border:1px solid var(--border-soft,#e5e7eb);padding:5px 10px;border-radius:6px;cursor:pointer;font-size:12px;display:none">↻</button>
      <button id="gp-stop" onclick="_glimiCtrl('stop')" style="background:transparent;color:var(--err,#ef4444);border:1px solid var(--err,#ef4444);padding:5px 10px;border-radius:6px;cursor:pointer;font-size:12px;display:none">■ 중지</button>
    `;
    if (spacer) spacer.parentNode.insertBefore(ctrl, spacer);
    else hdr.appendChild(ctrl);
    // 우측 기존 toggle 들 옆에 로그아웃
    const logout = document.createElement('button');
    logout.className = 'btn-icon';
    logout.title = '로그아웃';
    logout.textContent = '⏏';
    logout.onclick = window._glimiLogout;
    hdr.appendChild(logout);
    refresh();
    setInterval(refresh, 3000);
  }});
}})();
</script>
"""
    if "</body>" in dashboard_html:
        injected = dashboard_html.replace("</body>", platform_inject + "</body>", 1)
    else:
        injected = dashboard_html + platform_inject

    return HTMLResponse(content=injected)
