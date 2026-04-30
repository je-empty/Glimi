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

function renderCard(r) {
  const id = r.id;
  const status = r.status || 'pending';
  const sev = r.severity || 'med';
  const conf = r.confidence;
  const expanded = STATE.expanded.has(id);
  const summary = r.sera_summary || (r.payload?.repro || '').slice(0, 200) || '(no summary)';

  // 액션 버튼들
  const actions = [];
  if (status === 'analyzed' || status === 'needs_human_review') {
    actions.push(`<button class="approve" onclick="approveReq(${id})">✓ Approve</button>`);
    actions.push(`<button class="reject" onclick="rejectReq(${id})">Reject</button>`);
  } else if (status === 'approved') {
    actions.push(`<button class="unapprove" onclick="rejectReq(${id})">Unapprove</button>`);
  }

  // 메타 (commit / PR / 시간)
  const commit = r.commit_sha ? `<span class="commit">${esc(r.commit_sha.slice(0,8))}</span>` : '';
  const pr = r.pr_url ? `<a class="pr-link" href="${esc(r.pr_url)}" target="_blank" rel="noopener">PR ↗</a>` : '';
  const timeAgo = `<span>${fmtAgo(r.requested_at)} ago</span>`;

  // 상세 (expanded 시)
  let details = '';
  if (expanded) {
    const p = r.payload || {};
    const files = (r.files_hint_list || []).map(f => esc(f)).join(', ') || '(none)';
    details = `
      <span class="label">Channel</span>${esc(p.channel || '?')}
      <span class="label">Reproduce</span>${esc(p.repro || '?')}
      <span class="label">Expected</span>${esc(p.expected || '?')}
      <span class="label">Actual</span>${esc(p.actual || '?')}
      ${p.notes ? `<span class="label">Notes</span>${esc(p.notes)}` : ''}
      ${r.task_brief ? `<span class="label">Task brief (Claude Code 에 전달)</span><pre>${esc(r.task_brief)}</pre>` : ''}
      <span class="label">Files hint</span><span class="files">${files}</span>
      ${r.analysis_notes ? `<span class="label">Sera notes</span>${esc(r.analysis_notes)}` : ''}
      ${r.error ? `<span class="label" style="color:var(--err)">Error</span>${esc(r.error)}` : ''}
      <span class="label">Requested by</span>${esc(r.requested_by || '')} · ${fmtAgo(r.requested_at)} ago
    `;
  }

  return `
    <div class="card ${expanded ? 'expanded' : ''}" data-status="${esc(status)}">
      <div class="id-col">#${id}</div>

      <div class="badges">
        <span class="badge community">${esc(r.community_id || '?')}</span>
        <div class="status-row">
          <span class="badge status-${esc(status)}">${esc(status)}</span>
        </div>
        <div class="status-row">
          <span class="badge severity-${esc(sev)}">${esc(sev)}</span>
          ${conf ? `<span class="badge confidence-${esc(conf)}">${esc(conf)}</span>` : ''}
        </div>
      </div>

      <div class="summary">${esc(summary)}</div>
      <div class="details">${details}</div>
      <button class="toggle" onclick="toggleCard(${id})" style="grid-area: details; align-self: start;">
        ${expanded ? '▾ Hide details' : '▸ Show details'}
      </button>

      <div class="meta-col">
        ${pr}
        ${commit}
        ${timeAgo}
      </div>

      <div class="actions">
        ${actions.join('') || '<span style="color:var(--text-faint);font-size:11px;">—</span>'}
      </div>
    </div>
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
  } catch (e) { alert(`Approve failed: ${e.message}`); }
}

async function rejectReq(id) {
  if (!confirm(`Reject request #${id}?`)) return;
  try {
    await j(`/api/admin/dev-requests/${id}/reject`, { method: 'POST' });
    refreshList();
  } catch (e) { alert(`Reject failed: ${e.message}`); }
}

// ── Run / live output ────────────────────────────────────

async function runApproved() {
  const approved = STATE.items.filter(r => r.status === 'approved');
  if (approved.length === 0) return;
  if (!confirm(`Run ${approved.length} approved request(s)? This will stop all community bots, run Claude Code on a new branch, then create a PR.`)) return;
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
    alert(`Run failed: ${e.message}`);
  }
}

async function abortRun() {
  if (!STATE.activeRunId) return;
  if (!confirm('Abort the in-progress run? This kills the tmux session.')) return;
  try {
    await j(`/api/admin/dev-requests/run/${STATE.activeRunId}/abort`, { method: 'POST' });
  } catch (e) { alert(`Abort failed: ${e.message}`); }
}

async function mergeRun() {
  if (!STATE.activeRunId) return;
  if (!confirm('Merge this run\'s PR to develop? (squash + delete branch)')) return;
  try {
    const result = await j(`/api/admin/dev-requests/run/${STATE.activeRunId}/merge`, { method: 'POST' });
    alert(`Merged: ${result.pr_url}`);
    refreshList();
  } catch (e) { alert(`Merge failed: ${e.message}`); }
}

async function pollLive() {
  // 활성 run 자동 감지
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
      // run 끝나면 list 갱신
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
