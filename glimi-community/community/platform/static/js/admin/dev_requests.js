// /admin/dev-requests — Dev Requests 관리 페이지 클라이언트.
// 폴링: list 5s, 라이브 출력 1.5s.

const STATE = {
  filters: { community: '', status: '', severity: '' },
  items: [],
  liveByte: 0,
  activeRunId: null,
  expanded: new Set(),
};

function esc(s) { return String(s ?? '').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c])); }
function fmtAgo(iso) {
  if (!iso) return '';
  const dt = new Date(iso); if (isNaN(dt)) return '';
  const s = (Date.now() - dt.getTime()) / 1000;
  if (s < 60) return Math.floor(s) + 's';
  if (s < 3600) return Math.floor(s/60) + 'm';
  if (s < 86400) return Math.floor(s/3600) + 'h';
  return Math.floor(s/86400) + 'd';
}

async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

// ── Filter chips ────────────────────────────────────────

function bindChipGroup(groupId, key) {
  const root = document.getElementById(groupId);
  if (!root) return;
  root.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    const val = chip.dataset.val ?? '';
    STATE.filters[key] = val;
    [...root.querySelectorAll('.chip')].forEach(c => c.classList.toggle('active', (c.dataset.val ?? '') === val));
    refreshList();
  });
}

async function loadCommunityFilter() {
  const f = document.getElementById('f-community');
  if (!f) return;
  let data;
  try { data = await j('/api/admin/dev-requests/communities'); } catch { data = { items: [] }; }
  f.innerHTML = '<span class="chip active" data-val="">all</span>' +
    (data.items || []).map(c => `<span class="chip" data-val="${esc(c)}">${esc(c)}</span>`).join('');
  f.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    const val = chip.dataset.val ?? '';
    STATE.filters.community = val;
    [...f.querySelectorAll('.chip')].forEach(c => c.classList.toggle('active', (c.dataset.val ?? '') === val));
    refreshList();
  });
}

// ── List + render ───────────────────────────────────────

async function refreshList() {
  const params = new URLSearchParams();
  if (STATE.filters.community) params.set('community', STATE.filters.community);
  if (STATE.filters.status) params.set('status', STATE.filters.status);
  if (STATE.filters.severity) params.set('severity', STATE.filters.severity);
  let data;
  try { data = await j('/api/admin/dev-requests?' + params.toString()); } catch (e) {
    document.getElementById('grid').innerHTML = `<div class="empty-state">Failed to load: ${esc(e.message)}</div>`;
    return;
  }
  STATE.items = data.items || [];
  renderGrid();
}

function renderGrid() {
  const grid = document.getElementById('grid');
  const items = STATE.items;
  const countLabel = document.getElementById('count-label');
  countLabel.textContent = `${items.length} request${items.length === 1 ? '' : 's'}`;

  const approvedCount = items.filter(r => r.status === 'approved').length;
  const btnRun = document.getElementById('btn-run');
  btnRun.disabled = approvedCount === 0;
  btnRun.textContent = approvedCount === 0 ? '▶ Run all approved' : `▶ Run all approved (${approvedCount})`;

  if (items.length === 0) {
    grid.innerHTML = '<div class="empty-state">No requests match these filters.</div>';
    return;
  }

  grid.innerHTML = items.map(r => renderCard(r)).join('');
}

const STATUS_LABEL = {
  pending: '세나 분석 대기',
  analyzed: '검토 대기',
  approved: '승인됨 (실행 대기)',
  queued: '실행 대기열',
  processing: '작업 중',
  completed: '완료',
  failed: '실패',
  needs_human_review: '오너 판단 필요',
  rejected: '거부됨',
};

const SEVERITY_LABEL = { low: '낮음', med: '보통', high: '높음' };

function renderCard(r) {
  const id = r.id;
  const status = r.status || 'pending';
  const sev = r.severity || 'med';
  const conf = r.confidence;
  const expanded = STATE.expanded.has(id);
  const summary = r.sera_summary || (r.payload?.repro || '').slice(0, 240) || '(아직 분석 전)';

  // 액션
  const actions = [];
  if (status === 'analyzed' || status === 'needs_human_review') {
    actions.push(`<button class="btn-approve" onclick="approveReq(${id})">✓ 승인</button>`);
    actions.push(`<button class="btn-reject" onclick="rejectReq(${id})">거부</button>`);
  } else if (status === 'approved') {
    actions.push(`<button class="btn-unapprove" onclick="rejectReq(${id})">승인 취소</button>`);
  }

  // commit/PR
  const commitChip = r.commit_sha ? `<span class="chip-commit" title="commit ${esc(r.commit_sha)}">⌘ ${esc(r.commit_sha.slice(0,7))}</span>` : '';
  const prChip = r.pr_url ? `<a class="chip-pr" href="${esc(r.pr_url)}" target="_blank" rel="noopener">PR ↗</a>` : '';

  // 상세 (expanded)
  let detailsHtml = '';
  if (expanded) {
    const p = r.payload || {};
    const files = (r.files_hint_list || []);
    detailsHtml = `
      <div class="detail-grid">
        <section class="detail-section">
          <h4>📋 원본 보고서</h4>
          <div class="kv"><span class="k">발생 채널</span><span class="v">${esc(p.channel || '?')}</span></div>
          <div class="kv"><span class="k">재현 방법</span><span class="v">${esc(p.repro || '?')}</span></div>
          <div class="kv"><span class="k">기대 동작</span><span class="v">${esc(p.expected || '?')}</span></div>
          <div class="kv"><span class="k">실제 동작</span><span class="v">${esc(p.actual || '?')}</span></div>
          ${p.notes ? `<div class="kv"><span class="k">추가 메모</span><span class="v">${esc(p.notes)}</span></div>` : ''}
          <div class="kv"><span class="k">보고자</span><span class="v">${esc(r.requested_by || '')} · ${fmtAgo(r.requested_at)} 전</span></div>
        </section>
        ${r.task_brief ? `
        <section class="detail-section">
          <h4>📐 세나의 작업 지시 (Claude Code 가 받음)</h4>
          <pre class="task-brief">${esc(r.task_brief)}</pre>
          ${files.length ? `<div class="kv"><span class="k">관련 파일</span><span class="v files-list">${files.map(f => `<code>${esc(f)}</code>`).join(' ')}</span></div>` : ''}
          ${r.analysis_notes ? `<div class="kv"><span class="k">분석 메모</span><span class="v">${esc(r.analysis_notes)}</span></div>` : ''}
        </section>
        ` : ''}
        ${r.error ? `<section class="detail-section error"><h4>⚠ 실패 사유</h4><pre>${esc(r.error)}</pre></section>` : ''}
      </div>
    `;
  }

  return `
    <article class="dev-card" data-status="${esc(status)}">
      <div class="dev-card-main">
        <div class="dev-card-left">
          <div class="card-id">#${id}</div>
          <span class="dev-badge community" title="발생 커뮤니티">${esc(r.community_id || '?')}</span>
        </div>

        <div class="dev-card-body">
          <div class="card-row-1">
            <span class="dev-badge status status-${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>
            <span class="dev-badge sev severity-${esc(sev)}" title="심각도">${esc(SEVERITY_LABEL[sev] || sev)}</span>
            ${conf ? `<span class="dev-badge conf confidence-${esc(conf)}" title="세나 자체 판정">${conf === 'high' ? '명확한 수정' : '판단 모호'}</span>` : ''}
            <span class="card-time" title="${esc(r.requested_at || '')}">${fmtAgo(r.requested_at)} 전</span>
          </div>
          <div class="card-summary">${esc(summary)}</div>
          <div class="card-row-2">
            ${commitChip}
            ${prChip}
            <button class="btn-toggle" onclick="toggleCard(${id})">
              ${expanded ? '▾ 접기' : '▸ 자세히'}
            </button>
          </div>
        </div>

        <div class="dev-card-actions">
          ${actions.join('') || '<span class="no-action">—</span>'}
        </div>
      </div>
      ${detailsHtml}
    </article>
  `;
}

function toggleCard(id) {
  if (STATE.expanded.has(id)) STATE.expanded.delete(id); else STATE.expanded.add(id);
  renderGrid();
}

async function approveReq(id) {
  try {
    await j(`/api/admin/dev-requests/${id}/approve`, { method: 'POST' });
    refreshList();
  } catch (e) { alert(`승인 실패: ${e.message}`); }
}

async function rejectReq(id) {
  if (!confirm(`#${id} 을(를) 거부할까요?`)) return;
  try {
    await j(`/api/admin/dev-requests/${id}/reject`, { method: 'POST' });
    refreshList();
  } catch (e) { alert(`거부 실패: ${e.message}`); }
}

// ── Run / live output ────────────────────────────────────

async function runApproved() {
  const approved = STATE.items.filter(r => r.status === 'approved');
  if (approved.length === 0) return;
  if (!confirm(`승인된 ${approved.length}건을 실행할까요?\n\n진행 시:\n1. 모든 community 봇 정지\n2. dev-requests/run-{ts} 브랜치 생성\n3. Claude Code(Opus) 가 작업 + 개별 commit\n4. PR 자동 생성 (target: develop)\n5. 봇 재가동`)) return;
  try {
    const result = await j('/api/admin/dev-requests/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_ids: approved.map(r => r.id) }),
    });
    STATE.activeRunId = result.run_id;
    STATE.liveByte = 0;
    document.getElementById('live-panel').classList.add('visible');
    document.getElementById('live-output').textContent = '';
    document.getElementById('live-meta').textContent = `run #${result.run_id} · branch ${result.branch}`;
    refreshList();
  } catch (e) {
    alert(`Run 실패: ${e.message}`);
  }
}

async function abortRun() {
  if (!STATE.activeRunId) return;
  if (!confirm('진행 중인 run 을 중단할까요? tmux 세션이 강제 종료됩니다.')) return;
  try {
    await j(`/api/admin/dev-requests/run/${STATE.activeRunId}/abort`, { method: 'POST' });
  } catch (e) { alert(`중단 실패: ${e.message}`); }
}

async function mergeRun() {
  if (!STATE.activeRunId) return;
  if (!confirm('이 run 의 PR 을 develop 으로 merge 할까요? (squash + branch 삭제)')) return;
  try {
    const result = await j(`/api/admin/dev-requests/run/${STATE.activeRunId}/merge`, { method: 'POST' });
    alert(`Merged: ${result.pr_url}`);
    refreshList();
  } catch (e) { alert(`Merge 실패: ${e.message}`); }
}

async function pollLive() {
  if (!STATE.activeRunId) {
    try {
      const r = await j('/api/admin/dev-requests/run/active');
      if (r.active) {
        STATE.activeRunId = r.active.id;
        STATE.liveByte = 0;
        document.getElementById('live-panel').classList.add('visible');
        document.getElementById('live-output').textContent = '';
      }
    } catch {}
    return;
  }
  try {
    const r = await j(`/api/admin/dev-requests/run/${STATE.activeRunId}/live?since=${STATE.liveByte}`);
    if (r.bytes_read > 0) {
      const out = document.getElementById('live-output');
      out.textContent += r.content;
      STATE.liveByte = r.next_byte;
      out.scrollTop = out.scrollHeight;
    }
    document.getElementById('live-meta').textContent =
      `run #${STATE.activeRunId} · status: ${r.status || '?'}`;
    if (r.status === 'completed') {
      document.getElementById('btn-merge').style.display = 'inline-block';
    }
    if (r.finished || ['completed','failed','aborted'].includes(r.status)) {
      refreshList();
      if (r.status !== 'completed') {
        STATE.activeRunId = null;
      }
    }
  } catch (e) {
    console.warn('live poll failed', e);
  }
}

// ── Init ─────────────────────────────────────────────────

bindChipGroup('f-status', 'status');
bindChipGroup('f-severity', 'severity');
loadCommunityFilter().then(refreshList);
setInterval(refreshList, 5000);
setInterval(pollLive, 1500);
