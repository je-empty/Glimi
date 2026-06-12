// Glimi Dashboard — 단일 파일. 추후 모듈 분리 예정.

// ==== State ====
// community 는 서버에서 `window.__GLIMI_COMMUNITY__` 로 주입됨. URL 쿼리 fallback.
const params = new URLSearchParams(location.search);
let COMMUNITY = (typeof window !== 'undefined' && window.__GLIMI_COMMUNITY__) || params.get('community') || null;
let THEME = localStorage.getItem('glimi-theme') || 'light';
document.documentElement.setAttribute('data-theme', THEME);

// ==== i18n ====
// LANG_OVERRIDE: 'ko' | 'en' | null (null = 서버 설정 따라감)
// 번역 dict는 /api/i18n?lang=... 엔드포인트에서 로드 (i18n/dashboard.{ko,en}.json)
let LANG_OVERRIDE = localStorage.getItem('glimi-lang') || null;
let SERVER_LANG = 'ko';
let I18N_CACHE = {};  // lang → dict

async function loadLang(lang) {
  if (I18N_CACHE[lang]) return I18N_CACHE[lang];
  try {
    const r = await fetch(`/api/i18n?lang=${encodeURIComponent(lang)}`);
    I18N_CACHE[lang] = await r.json();
  } catch {
    I18N_CACHE[lang] = {};
  }
  return I18N_CACHE[lang];
}

function currentLang() { return LANG_OVERRIDE || SERVER_LANG || 'ko'; }
function t(key, vars) {
  const dict = I18N_CACHE[currentLang()] || I18N_CACHE.ko || {};
  let s = dict[key] || (I18N_CACHE.ko && I18N_CACHE.ko[key]) || key;
  if (vars) Object.entries(vars).forEach(([k, v]) => { s = s.replace(`{${k}}`, v); });
  return s;
}

// === removed inline I18N dict (moved to i18n/dashboard.{ko,en}.json) ===
const I18N_UNUSED_OLD = {
  ko: {
    // Banners
    offline_title: '오프라인',
    offline_msg: '커뮤니티 서버가 실행 중이 아님. 마지막 스냅샷 표시 중 (실시간 아님)',
    offline_last: '마지막 활동',
    empty_community_title: '📭 이 커뮤니티는 비어있어요',
    empty_community_msg: '아직 에이전트나 대화가 없어요. 커뮤니티 서버를 시작하면 데이터가 채워집니다.',
    empty_community_hint: '서버 시작',
    // KPI
    kpi_server: 'Server Status',
    kpi_bot: 'Discord Bot',
    kpi_owner: 'Owner',
    kpi_scene: 'Active Scene',
    kpi_msgs: 'Messages',
    online: '● Online',
    offline_short: '○ Offline',
    running: '● Running',
    stopped: '○ Stopped',
    nothing_active: 'nothing active',
    // Sections
    section_active_members: 'Agents',
    section_recent_conv: 'Recent Conversations',
    // Tabs
    tab_overview: 'Overview', tab_agents: 'Agents', tab_channels: 'Channels',
    tab_messages: 'Messages', tab_scenes: 'Scenes', tab_events: 'Events',
    tab_health: 'Health', tab_sync: 'Sync', tab_dev: 'Dev', tab_usage: 'Usage',
    tab_supervisors: 'Supervisors', tab_logs: 'Logs',
    // Buttons
    btn_server_start: '▶ 서버 시작',
    btn_server_stop: '⏸ 서버 중단',
    btn_server_restart: '↻ 재시작',
    btn_scan: '🔍 Scan Discord',
    btn_sync: '▶ Full Sync',
    btn_restore: '↻ Restore Messages',
    btn_clear_msgs: '🧹 메시지 전체 삭제 (DB만)',
    btn_delete_ch: '🗑 채널 삭제',
    btn_refresh: '새로고침',
    btn_empty_trash: 'Empty Trash',
    btn_close: '닫기',
    // Section titles
    sec_processes: 'Processes',
    sec_glimi_resources: 'Glimi Resource Usage',
    sec_system_resources: 'System Resources',
    sec_server_control: 'Server Control',
    sec_sync_actions: 'Sync Actions',
    sec_trash: 'Trash',
    sec_db_channels: 'DB-registered Channels',
    sec_profile: 'Profile',
    sec_relationships: 'Relationships',
    sec_memory: 'Memory',
    sec_thinking_logs: 'Thinking Logs',
    sec_recent_chat: 'Recent Chat',
    sec_participants: 'Participants',
    sec_all_messages: 'All Messages',
    sec_actions: 'Actions',
    sec_connection_graph: 'Connection Graph',
    // Status
    status_active: '진행 중',
    status_completed: '완료',
    status_not_started: '시작 전',
    active_badge: '● ACTIVE',
    idle_badge: '○ IDLE',
    intervening_badge: '● INTERVENING',
    live_label: '● LIVE',
    thinking: '생각 중',
    speaking: '응답 중',
    calm_idle: '평온 · 모두 대기 중',
    // Misc
    loading: '로딩 중…',
    no_data: '데이터 없음',
    no_members: '멤버 없음',
    no_channels: '채널 없음',
    no_events: '기록된 이벤트 없음',
    no_scenes: '씬 정보 없음',
    no_supervisors: '등록된 감시자 없음',
    no_msgs: '대화 없음',
    no_trash: '휴지통 비어있음',
    // Field labels
    f_age: '나이', f_mbti: 'MBTI', f_enneagram: '에니어그램', f_traits: '성격 특성',
    f_emotion: '감정', f_status: '상태', f_model: '모델', f_owner: '오너',
    f_background: '배경',
    f_started: '시작', f_completed: '완료', f_last_active: '마지막 활동',
    // Sync
    sync_guard_running: 'ℹ 서버 실행 중 — Sync 버튼 클릭 시 자동으로 서버 중단 → 작업 → 재시작 진행. 취소 버튼 제공됨.',
    sync_guard_stopped: '○ 서버 오프라인 — 모든 sync 작업 즉시 가능.',
    sync_hint: 'Discord 서버와 DB 사이 상태를 맞추는 작업. 서버 실행 중이면 자동 중단·작업·재시작.',
    trash_hint: '휴지통 — 채널/메시지 삭제 시 완전 삭제 대신 여기로 옮겨짐. 실수 복구용 안전망.',
    // Confirm dialogs
    confirm_clear: '#{ch}의 DB 메시지 전체 삭제. Discord 채널은 유지. 진행?',
    confirm_delete_ch: '채널 #{ch} 완전 삭제. 복구 어려움. 진행?',
    confirm_trash_msg: '이 메시지를 trash로 옮길까? (복구 가능)',
    confirm_empty_trash: 'Trash 전체 비우기. 되돌릴 수 없음. 진행?',
    confirm_stop_server: '커뮤니티 서버 중단?',
    confirm_restart_server: '서버 재시작? (10~20초 소요)',
    confirm_sync_restart: '{act}를 실행하려면 서버 일시 중단이 필요. 중단 → 실행 → 재시작 자동으로 진행할까?',
  },
  en: {
    offline_title: 'Offline',
    offline_msg: 'Community server is not running. Showing last snapshot (not live).',
    offline_last: 'last activity',
    empty_community_title: '📭 This community is empty',
    empty_community_msg: "No agents or conversations yet. Start the community server to populate data.",
    empty_community_hint: 'Start server',
    kpi_server: 'Server Status', kpi_bot: 'Discord Bot', kpi_owner: 'Owner',
    kpi_scene: 'Active Scene', kpi_msgs: 'Messages',
    online: '● Online', offline_short: '○ Offline',
    running: '● Running', stopped: '○ Stopped',
    nothing_active: 'nothing active',
    section_active_members: 'Agents', section_recent_conv: 'Recent Conversations',
    tab_overview: 'Overview', tab_agents: 'Agents', tab_channels: 'Channels',
    tab_messages: 'Messages', tab_scenes: 'Scenes', tab_events: 'Events',
    tab_health: 'Health', tab_sync: 'Sync', tab_dev: 'Dev', tab_usage: 'Usage',
    tab_supervisors: 'Supervisors', tab_logs: 'Logs',
    btn_server_start: '▶ Start Server', btn_server_stop: '⏸ Stop Server',
    btn_server_restart: '↻ Restart',
    btn_scan: '🔍 Scan Discord', btn_sync: '▶ Full Sync', btn_restore: '↻ Restore Messages',
    btn_clear_msgs: '🧹 Clear All Messages (DB only)',
    btn_delete_ch: '🗑 Delete Channel',
    btn_refresh: 'Refresh', btn_empty_trash: 'Empty Trash', btn_close: 'Close',
    sec_processes: 'Processes', sec_glimi_resources: 'Glimi Resource Usage',
    sec_system_resources: 'System Resources', sec_server_control: 'Server Control',
    sec_sync_actions: 'Sync Actions', sec_trash: 'Trash',
    sec_db_channels: 'DB-registered Channels',
    sec_profile: 'Profile', sec_relationships: 'Relationships',
    sec_memory: 'Memory', sec_thinking_logs: 'Thinking Logs',
    sec_recent_chat: 'Recent Chat', sec_participants: 'Participants',
    sec_all_messages: 'All Messages', sec_actions: 'Actions',
    sec_connection_graph: 'Connection Graph',
    status_active: 'Active', status_completed: 'Completed', status_not_started: 'Not Started',
    active_badge: '● ACTIVE', idle_badge: '○ IDLE', intervening_badge: '● INTERVENING',
    live_label: '● LIVE',
    thinking: 'thinking', speaking: 'speaking',
    calm_idle: 'calm · all idle',
    loading: 'Loading…', no_data: 'No data',
    no_members: 'No members', no_channels: 'No channels',
    no_events: 'No events recorded',
    no_scenes: 'No scenes', no_supervisors: 'No supervisors registered',
    no_msgs: 'No conversations', no_trash: 'Trash is empty',
    f_age: 'Age', f_mbti: 'MBTI', f_enneagram: 'Enneagram', f_traits: 'Traits',
    f_emotion: 'Emotion', f_status: 'Status', f_model: 'Model', f_owner: 'Owner',
    f_background: 'Background',
    f_started: 'Started', f_completed: 'Completed', f_last_active: 'last active',
    sync_guard_running: 'ℹ Server is running — clicking a sync button will auto stop server → run → restart. A confirm dialog lets you cancel.',
    sync_guard_stopped: '○ Server offline — all sync actions available.',
    sync_hint: 'Synchronize state between Discord and the DB. Server is auto-stopped/restarted as needed.',
    trash_hint: 'Trash — deleted channels/messages go here first. Safety net for accidental deletion.',
    confirm_clear: 'Clear all messages in #{ch} from DB? Discord channel will be kept.',
    confirm_delete_ch: 'Delete channel #{ch} completely? Hard to recover.',
    confirm_trash_msg: 'Move this message to trash? (recoverable)',
    confirm_empty_trash: 'Empty the Trash permanently? This cannot be undone.',
    confirm_stop_server: 'Stop the community server?',
    confirm_restart_server: 'Restart the server? (takes 10-20s)',
    confirm_sync_restart: 'Running {act} needs a temporary server stop. Auto stop → run → restart. Continue?',
  },
};
// (duplicate currentLang/t removed — defined earlier using fetched I18N_CACHE)

// ==== Utils ====
function esc(s) { return String(s ?? '').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c])); }

// Model 표시: " · " 구분자로 여러 모델 → 각 모델별 chip 블록
//   모델 이름에서 family 추출 (haiku / sonnet / opus / gpt / gemini) → 일관된 색
//   "+" 구분자 제거 — chip 자체로 구분
function _modelFamilyClass(p) {
  const s = String(p).toLowerCase();
  if (s.includes('haiku')) return 'm-haiku';
  if (s.includes('sonnet')) return 'm-sonnet';
  if (s.includes('opus')) return 'm-opus';
  if (s.includes('gpt') || s.includes('o1') || s.includes('o3')) return 'm-gpt';
  if (s.includes('gemini')) return 'm-gemini';
  return '';
}
function _modelKindIcon(modelId) {
  // 모델 id 로 cloud/local 구분 아이콘 — ☁️/🖥️.
  if (!modelId) return '';
  const s = String(modelId).toLowerCase();
  if (s.startsWith('claude-') || s.startsWith('gpt-') || s.startsWith('gemini-') || s.startsWith('openai')) {
    return '☁️';
  }
  if (s.startsWith('ollama:') || s.startsWith('vllm:') || s.startsWith('llamacpp:') || s.startsWith('local:') || s.includes('llama') || s.includes('qwen') || s.includes('mistral')) {
    return '🖥️';
  }
  return '';
}

function renderModelChips(d, compact) {
  if (!d || !d.model) return '';
  const raw = String(d.model);
  const parts = raw.split(/\s*·\s*/).map(s => s.trim()).filter(Boolean);
  const provider = d.provider || '';
  const override = d.model_override ? ' override' : '';
  const title = d.model_override ? 'per-agent override' : 'default';
  const chips = parts.map(p => {
    const fam = _modelFamilyClass(p);
    const classes = ['model-tag', provider, fam, override.trim()].filter(Boolean).join(' ');
    const icon = _modelKindIcon(p);
    return `<span class="${classes}" title="${esc(title)}">${icon ? icon + ' ' : ''}${esc(p)}</span>`;
  }).join('');
  const suffix = compact
    ? ''
    : (d.model_override
        ? ' <small style="color:var(--accent)">override</small>'
        : '<small style="color:var(--text-faint)"> · default</small>');
  return `<span class="model-chip-row">${chips}</span>${suffix}`;
}
async function j(u) { try { const r = await fetch(u); return await r.json(); } catch { return null; } }
function q(u) { return COMMUNITY ? `${u}${u.includes('?') ? '&' : '?'}community=${encodeURIComponent(COMMUNITY)}` : u; }
function atBottom(el) { return el.scrollHeight - el.scrollTop - el.clientHeight < 80; }
function classifyLog(line) {
  if (/❌|FATAL|Exception|failed|오류/.test(line) || /\berror\b/i.test(line)) return 'err';
  if (/⚠|warn|경고/i.test(line)) return 'warn';
  if (/✓|완료|ready|success|Tool registered/i.test(line)) return 'ok';
  if (/\[Tool\]|<tools>|<\/tools>|<call |<\/call>|<tool_result/i.test(line)) return 'tool';
  return '';
}
function fmtElapsed(secs) {
  if (!secs) return '0s';
  if (secs < 60) return `${Math.floor(secs)}s`;
  return `${Math.floor(secs/60)}:${String(Math.floor(secs%60)).padStart(2,'0')}`;
}
function fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

function renderGpuCard(gpu, sysMemTotal, sysMemUsed) {
  if (!gpu || !gpu.supported) {
    return `<div class="health-card" style="opacity:0.5">
      <h4>GPU</h4>
      <div class="big" style="font-size:13px;color:var(--text-faint)">감지되지 않음</div>
      <div class="sub">${esc(gpu?.platform || 'unknown platform')}</div>
    </div>`;
  }
  if (gpu.unified_memory) {
    // Apple Silicon: unified memory — GPU VRAM = system RAM 공유
    const pct = sysMemTotal ? (sysMemUsed / sysMemTotal * 100).toFixed(1) : 0;
    return `<div class="health-card">
      <h4>GPU · ${esc(gpu.name || 'Apple Silicon')}</h4>
      <div class="big" style="font-size:15px">${esc(gpu.name || 'Apple Silicon')}${gpu.cores ? ` · ${gpu.cores} cores` : ''}</div>
      <div class="sub">Unified Memory (${fmtBytes(sysMemTotal)} shared w/ RAM)</div>
      <div class="disk-bar"><span style="width:${pct}%"></span></div>
    </div>`;
  }
  // Dedicated GPU (e.g. NVIDIA)
  const vramPct = gpu.vram_total_bytes ? (gpu.vram_used_bytes / gpu.vram_total_bytes * 100).toFixed(1) : 0;
  return `<div class="health-card">
    <h4>GPU · ${esc(gpu.name || 'GPU')}</h4>
    <div class="big">${gpu.utilization_pct}<small style="font-size:13px;color:var(--text-dim)">%</small></div>
    <div class="sub">VRAM: ${fmtBytes(gpu.vram_used_bytes)} / ${fmtBytes(gpu.vram_total_bytes)} · ${vramPct}%</div>
    <div class="disk-bar"><span style="width:${vramPct}%"></span></div>
  </div>`;
}
function roleClass(m) {
  if (m.is_user) return 'user';
  const id = m.speaker_id || '';
  if (id.includes('mgr')) return 'mgr';
  if (id.includes('creator')) return 'creator';
  return 'persona';
}
function chIcon(ch) {
  if (!ch) return '📝';
  if (ch.startsWith('mgr')) return '📋';
  if (ch.startsWith('dm-')) return '💬';
  if (ch.startsWith('group-')) return '👥';
  if (ch.startsWith('internal-dm')) return '🔒';
  if (ch.startsWith('internal-group')) return '🔒👥';
  return '📝';
}

// ==== Theme ====
function _themeIcon() {
  document.getElementById('theme-toggle').innerHTML =
    `<i class="ti ${THEME === 'light' ? 'ti-sun' : 'ti-moon'}" aria-hidden="true"></i>`;
}
document.getElementById('theme-toggle').addEventListener('click', () => {
  THEME = THEME === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', THEME);
  _themeIcon();
  localStorage.setItem('glimi-theme', THEME);
});
_themeIcon();

// ==== 레일 슬라이딩 썸 (je-empty pillseg 모션) ====
const _railEl = document.getElementById('tabs');
const _railThumb = document.createElement('span');
_railThumb.className = 'rail-thumb';
_railEl.appendChild(_railThumb);
function positionRailThumb(instant) {
  const btn = _railEl.querySelector('button.active');
  if (!btn || !btn.offsetHeight) return;
  if (instant) _railThumb.style.transition = 'none';
  _railThumb.style.transform = 'translateY(' + btn.offsetTop + 'px)';
  _railThumb.style.height = btn.offsetHeight + 'px';
  _railThumb.classList.add('ready');
  if (instant) { void _railThumb.offsetHeight; _railThumb.style.transition = ''; }
}
// 탭 클릭 → active 토글이 끝난 다음 태스크에서 이동 (rAF 는 백그라운드 탭에서 굶을 수 있어 setTimeout)
_railEl.addEventListener('click', () => setTimeout(() => positionRailThumb(false), 0));
window.addEventListener('resize', () => positionRailThumb(true));
// supervisor 토글로 sup-tab 표시가 바뀌면 오프셋 재계산
document.getElementById('supervisor-toggle')?.addEventListener('click', () =>
  setTimeout(() => positionRailThumb(true), 0));
positionRailThumb(true);

// ==== Supervisor view toggle ====
let SHOW_SUP = localStorage.getItem('glimi-show-supervisors') === 'true';
function applySupVisibility() {
  document.body.classList.toggle('show-supervisors', SHOW_SUP);
  document.getElementById('supervisor-toggle').classList.toggle('active', SHOW_SUP);
  // 비활성화 시 Supervisors 탭에 있었으면 overview로 돌리기
  if (!SHOW_SUP) {
    const supView = document.getElementById('view-supervisors');
    if (supView && supView.classList.contains('active')) {
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      document.querySelectorAll('nav.tabs button').forEach(b => b.classList.remove('active'));
      document.getElementById('view-overview').classList.add('active');
      document.querySelector('nav.tabs button[data-tab="overview"]').classList.add('active');
    }
  }
}
applySupVisibility();
document.getElementById('supervisor-toggle').addEventListener('click', () => {
  SHOW_SUP = !SHOW_SUP;
  localStorage.setItem('glimi-show-supervisors', SHOW_SUP ? 'true' : 'false');
  applySupVisibility();
  lastGraphSig = null;  // supervisor 노드 출현/사라짐 → 재렌더
  tick();
});

// ==== Language toggle (flag button + dropdown menu) ====
const LANG_OPTIONS = [
  { id: null,  flag: '🌐', label: 'Auto' },
  { id: 'ko',  flag: '🇰🇷', label: '한국어' },
  { id: 'en',  flag: '🇺🇸', label: 'English' },
];
function applyLangLabel() {
  const btn = document.getElementById('lang-toggle');
  if (!btn) return;
  const l = currentLang();
  // 버튼에는 항상 현재 활성 언어의 국기만 (Auto면 서버언어 국기)
  const flag = LANG_OVERRIDE
    ? (LANG_OVERRIDE === 'ko' ? '🇰🇷' : '🇺🇸')
    : (l === 'ko' ? '🇰🇷' : '🇺🇸');
  btn.textContent = flag;
  btn.title = LANG_OVERRIDE
    ? (LANG_OVERRIDE === 'ko' ? '한국어 (고정) — 클릭하여 변경' : 'English (fixed) — click to change')
    : `Auto — server: ${SERVER_LANG.toUpperCase()}`;
  renderLangMenu();
  applyStaticI18n();
}
function renderLangMenu() {
  const menu = document.getElementById('lang-menu');
  if (!menu) return;
  menu.innerHTML = LANG_OPTIONS.map(opt => {
    const active = (opt.id === LANG_OVERRIDE) || (opt.id === null && !LANG_OVERRIDE);
    const sub = opt.id === null ? ` <span style="color:var(--text-faint);font-size:11px">(${SERVER_LANG.toUpperCase()})</span>` : '';
    return `<div class="li ${active ? 'active' : ''}" data-lang="${opt.id === null ? '' : opt.id}">
      <span class="li-flag">${opt.flag}</span>
      <span class="li-name">${opt.label}${sub}</span>
      <span class="li-check"></span>
    </div>`;
  }).join('');
  menu.querySelectorAll('.li').forEach(el => {
    el.addEventListener('click', () => {
      const v = el.dataset.lang;
      LANG_OVERRIDE = v ? v : null;
      if (LANG_OVERRIDE) localStorage.setItem('glimi-lang', LANG_OVERRIDE);
      else localStorage.removeItem('glimi-lang');
      menu.classList.remove('open');
      applyLangLabel();
      tick();
    });
  });
}
function applyStaticI18n() {
  // 탭 라벨
  const tabMap = {
    overview: 'tab_overview', agents: 'tab_agents', channels: 'tab_channels',
    messages: 'tab_messages', scenes: 'tab_scenes', events: 'tab_events',
    health: 'tab_health', sync: 'tab_sync', dev: 'tab_dev', usage: 'tab_usage',
    supervisors: 'tab_supervisors', logs: 'tab_logs',
  };
  document.querySelectorAll('nav.tabs button[data-tab]').forEach(btn => {
    const k = tabMap[btn.dataset.tab];
    if (!k) return;
    const cnt = btn.querySelector('.count');
    const cntHtml = cnt ? cnt.outerHTML : '';
    // 템플릿에서 서버 렌더한 아이콘 보존 (i18n 재빌드가 innerHTML 갈아끼우며 날리던 것)
    const em = btn.querySelector('.tab-emoji');
    const emHtml = em ? em.outerHTML : '';
    btn.innerHTML = `${emHtml}<span class="tab-label">${t(k)}</span> ${cntHtml}`;
  });
  // KPI labels
  const kpiMap = [['kpi-server','kpi_server'],['kpi-bot','kpi_bot'],['kpi-user','kpi_owner'],['kpi-scene','kpi_scene'],['kpi-msgs','kpi_msgs']];
  kpiMap.forEach(([id, k]) => {
    const el = document.getElementById(id);
    if (el && el.previousElementSibling && el.previousElementSibling.classList.contains('label')) {
      el.previousElementSibling.textContent = t(k);
    }
  });
  // Detail close button
  const closeBtn = document.getElementById('d-close');
  if (closeBtn) closeBtn.textContent = t('btn_close');
}
document.getElementById('lang-toggle').addEventListener('click', (ev) => {
  ev.stopPropagation();
  const menu = document.getElementById('lang-menu');
  if (!menu) return;
  renderLangMenu();
  menu.classList.toggle('open');
});
document.addEventListener('click', (ev) => {
  const wrap = document.getElementById('lang-switcher-wrap');
  if (!wrap) return;
  if (!wrap.contains(ev.target)) {
    document.getElementById('lang-menu')?.classList.remove('open');
  }
});

// ==== Tabs ====
let _justEnteredTimer = null;
function markJustEntered(view) {
  // 카드 레벨 스태거 발동 창 — 폴링 재렌더가 이 창 밖이면 재발동 안 함.
  document.querySelectorAll('.view.just-entered').forEach(v => v.classList.remove('just-entered'));
  if (_justEnteredTimer) clearTimeout(_justEnteredTimer);
  // 강제 reflow 로 직전 제거가 반영되게 → 같은 탭 재진입에도 재생
  void view.offsetWidth;
  view.classList.add('just-entered');
  _justEnteredTimer = setTimeout(() => view.classList.remove('just-entered'), 1500);
}
document.querySelectorAll('nav.tabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('nav.tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    btn.classList.add('active');
    const view = document.getElementById('view-' + btn.dataset.tab);
    view.classList.add('active');
    markJustEntered(view);
    if (btn.dataset.tab === 'achievements') {
      loadAchievements();
    }
  });
});

// ==== Renderers ====
function avatarHtml(a, size='', opts={}) {
  const cls = ['avatar', size];
  if (a.thinking) cls.push('thinking-ring');
  else if (a.speaking) cls.push('speaking-ring');
  else if (a.intensity >= 9) cls.push('ring-9');
  else if (a.intensity >= 7) cls.push('ring-7');
  else if (a.intensity >= 5) cls.push('ring-5');
  const src = `/api/avatar?id=${encodeURIComponent(a.id)}${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
  // 평온 + 낮은 강도면 emoji badge 숨김
  const hideBadge = a.emotion === '평온' || opts.hideBadge;
  const clickOpen = opts.clickOpen !== false;
  const onclick = clickOpen ? `onclick="event.stopPropagation(); openFullAvatar('${esc(a.id)}', '${esc(a.name)}')"` : '';
  return `<div class="${cls.filter(Boolean).join(' ')}" title="${esc(a.name)}" ${onclick}>
    <img src="${src}" alt="${esc(a.name)}" decoding="async" onerror="this.style.display='none'">
    <span class="emoji-badge ${hideBadge ? 'hidden' : ''}">${a.emoji}</span>
  </div>`;
}

function miniAvatarHtml(speakerId, isUser, speakerName) {
  if (isUser) {
    const initial = (speakerName || '?').slice(0, 1);
    return `<div class="msg-avatar user" title="${esc(speakerName)}">${esc(initial)}</div>`;
  }
  const src = `/api/avatar?id=${encodeURIComponent(speakerId)}${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
  return `<div class="msg-avatar" title="${esc(speakerName)}" onclick="openFullAvatar('${esc(speakerId)}', '${esc(speakerName)}')">
    <img src="${src}" alt="${esc(speakerName)}" decoding="async" onerror="this.parentElement.innerHTML='<div style=&quot;display:flex;align-items:center;justify-content:center;width:100%;height:100%;font-size:11px;color:var(--text-faint)&quot;>?</div>'">
  </div>`;
}

function renderAgent(a, clickable=true) {
  // status 'inactive' 면 카드도 dim — dev agent 가 큐 비어있을 때.
  // live 상태 (thinking/speaking) 가 inactive 보다 우선.
  const isInactive = a.status === 'inactive' && !a.thinking && !a.speaking;
  const cls = ['agent-card', a.type,
               a.thinking ? 'thinking' : '',
               a.speaking ? 'speaking' : '',
               isInactive ? 'inactive' : ''].filter(Boolean).join(' ');
  const pct = Math.min(100, (a.intensity || 0) * 10);
  const elapsed = a.thinking ? a.thinking_seconds : a.speaking ? a.speaking_seconds : 0;
  const dot = a.status === 'active' ? 'active' : '';

  // expanded section — 로그/채팅 미리보기. progress 바는 위쪽 .state-bar 가 담당.
  let expanded = '';
  if (a.thinking || a.speaking) {
    const logs = (a._logs || []).map(l => `<div class="logline">${esc(l)}</div>`).join('');
    const chat = (a._chat || []).map(c =>
      `<div class="cline ${c.is_user ? 'user' : ''}"><b>${esc(c.speaker)}:</b>${esc((c.message||'').slice(0, 90))}</div>`
    ).join('');
    if (logs || chat) {
      expanded = `<div class="agent-expanded">
        ${logs ? `<div class="agent-logs">${logs}</div>` : ''}
        ${chat ? `<div class="agent-chat">${chat}</div>` : ''}
      </div>`;
    }
  }

  const onclick = clickable ? `onclick="openAgent('${esc(a.id)}')"` : '';
  // last_active 를 상대 시간으로 표시. _parseServerTs 로 aware/naive(KST fallback) 모두 처리.
  let agoText = '';
  if (a.last_active) {
    try {
      const dt = _parseServerTs(a.last_active);
      if (dt && !isNaN(dt.getTime())) {
        const secs = (Date.now() - dt.getTime()) / 1000;
        if (secs < 60) agoText = `${Math.floor(secs)}s`;
        else if (secs < 3600) agoText = `${Math.floor(secs/60)}m`;
        else if (secs < 86400) agoText = `${Math.floor(secs/3600)}h`;
        else agoText = `${Math.floor(secs/86400)}d`;
      }
    } catch {}
  }
  return `<div class="${cls}" ${onclick}>
    <div class="agent-head">
      ${avatarHtml(a)}
      <div class="info">
        <div class="name-row">
          <span class="status-dot ${dot}"></span>
          <span class="name">${esc(a.name)}</span>
          <span class="type-tag ${a.type}">${esc(a.type)}</span>
        </div>
        <div class="agent-meta">
          <span class="emotion-label" title="강도 ${a.intensity || 0}/10">${esc(a.emotion)}</span>
          <span class="intensity-mini band-${a.intensity_band || 'low'}" title="감정 강도 ${a.intensity || 0}/10">
            <span style="width:${Math.min(100, (a.intensity||0)*10)}%"></span>
          </span>
          ${a.mbti ? `<span class="sep">·</span><span>${esc(a.mbti)}</span>` : ''}
          ${a.age ? `<span class="sep">·</span><span>${a.age}y</span>` : ''}
        </div>
      </div>
    </div>
    <div class="state-bar">
      <div class="state-bar-fill"></div>
      <div class="state-bar-shine"></div>
      <div class="state-bar-text">
        ${a.thinking ? '<i class="ti ti-brain" aria-hidden="true"></i> Thinking<span class="state-dots"></span>' : (a.speaking ? '<i class="ti ti-message-circle" aria-hidden="true"></i> Speaking<span class="state-dots"></span>' : '')}
        ${(a.thinking || a.speaking) ? `<span style="opacity:0.75;font-weight:400;font-size:11px;letter-spacing:0">${fmtElapsed(elapsed)}</span>` : ''}
      </div>
    </div>
    <div class="agent-footer">
      ${a.model ? renderModelChips(a, true) : '<span></span>'}
      ${agoText ? `<span title="마지막 활동">${agoText} ago</span>` : ''}
    </div>
    ${expanded}
  </div>`;
}

function renderHero(snap) {
  const m = snap.meta;
  const persona = snap.agents.filter(a => a.type === 'persona');
  // dev (세나) 는 슈퍼바이저 보기 모드 ON 일 때만 hero 에 노출. mgr/creator/persona 만 default.
  const mgrs = snap.agents.filter(a => a.type !== 'persona' && (SHOW_SUP || a.type !== 'dev'));
  const all = [...mgrs, ...persona];
  const avatarsHtml = all.slice(0, 8).map(a => avatarHtml(a, 'xl')).join('');
  const active = snap.agents.filter(a => a.thinking || a.speaking);
  const offline = !snap.bot.bot_alive;
  let activeText;
  if (offline) {
    activeText = `<span style="color:var(--text-dim)">서버 오프라인 · 마지막 스냅샷</span>`;
  } else if (active.length) {
    const names = active.map(a => `<b style="color:${a.thinking ? 'var(--thinking)' : 'var(--speaking)'}">${esc(a.name)}</b>`).join(', ');
    const tAct = active.some(x => x.thinking);
    const sAct = active.some(x => x.speaking);
    const verb = tAct && sAct ? '생각 · 응답 중' : tAct ? '생각 중' : '응답 중';
    activeText = `${names} ${verb}`;
  } else {
    activeText = `<span style="color:var(--text-dim)">평온 · 모두 대기 중</span>`;
  }

  const userName = m.user_name || '—';
  const phase = m.tutorial_phase || '—';
  const msgCount = snap.total_messages || 0;
  const cm = snap.community_meta || {};
  const displayName = cm.name || snap.community_id;
  const hasSeparateName = cm.name && cm.name !== snap.community_id;
  const descText = cm.description || '';

  return `<div class="hero-row">
    <div class="hero-avatars">
      ${avatarsHtml || '<div style="color:var(--text-faint);padding:16px 0">no agents yet</div>'}
    </div>
    <div class="hero-text" style="flex:1">
      <h1>
        <span class="sv-name">${esc(displayName)}</span>
        ${hasSeparateName ? `<span style="color:var(--text-faint);font-weight:400;font-size:0.55em;margin-left:10px;font-family:'JetBrains Mono',monospace;vertical-align:middle">${esc(snap.community_id)}</span>` : ''}
      </h1>
      ${descText ? `<p style="color:var(--text-dim);margin-top:4px">${esc(descText)}</p>` : ''}
      <p style="margin-top:6px">${activeText}</p>
    </div>
  </div>`;
}

function openImgLightbox(src, caption) {
  const box = document.getElementById('lightbox');
  const img = document.getElementById('lightbox-img');
  const cap = document.getElementById('lightbox-caption');
  img.src = src;
  cap.textContent = caption || '';
  box.classList.add('open');
}

function openFullAvatar(agentId, name) {
  const src = `/api/avatar?id=${encodeURIComponent(agentId)}&variant=full${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
  openImgLightbox(src, name || agentId);
}

// 모든 <img> 클릭 시 자동으로 lightbox 띄우기 (delegation)
document.addEventListener('click', (e) => {
  const img = e.target.closest('img');
  if (!img) return;
  // 이미 lightbox 안의 이미지거나 미니 상태면 스킵
  if (img.closest('.lightbox')) return;
  // 아바타/로고는 별도 핸들러 우선 (onclick이 있으면 자동 스킵)
  if (img.closest('[onclick]') && img.closest('[onclick]') !== img) return;
  // 그 외 일반 이미지: 원본 띄우기
  e.stopPropagation();
  openImgLightbox(img.src, img.alt || '');
});

function _fmtMsgTime(iso) {
  // 뷰어 로컬 tz 변환. 오늘 메시지는 HH:MM, 그 외는 "MM-DD HH:MM".
  const d = _parseServerTs(iso);
  if (!d || isNaN(d.getTime())) return String(iso || '');
  const now = new Date();
  const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
  }
  return d.toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

function renderMessage(m) {
  return `<div class="msg ${roleClass(m)}">
    ${miniAvatarHtml(m.speaker_id, m.is_user, m.speaker)}
    <div class="msg-body">
      <div class="head">
        <span class="who">${esc(m.speaker)}</span>
        <span class="ch" onclick="event.stopPropagation(); openChannel('${esc(m.channel)}')">#${esc(m.channel)}</span>
        <span class="ts" title="${esc(m.timestamp || '')}">${esc(_fmtMsgTime(m.timestamp))}</span>
      </div>
      <div class="text">${esc(m.message)}</div>
    </div>
  </div>`;
}

function renderChannelCard(c) {
  return `<div class="channel-card kind-${c.kind}" onclick="openChannel('${esc(c.name)}')">
    <div class="name">${esc(c.name)}</div>
    <div class="meta">
      <span>${c.msg_count} msgs</span>
      <span class="sep">·</span>
      <span>${c.participant_count}명</span>
      <span class="sep">·</span>
      <span>${esc(c.last_ago || '—')}</span>
    </div>
  </div>`;
}

function renderChannelsGrouped(channels) {
  const groups = { mgr: [], dm: [], group: [], 'internal-dm': [], 'internal-group': [] };
  channels.forEach(c => { (groups[c.kind] || groups.mgr).push(c); });
  const labels = {
    'mgr': 'Manager',
    'dm': 'DM',
    'group': 'Group',
    'internal-dm': 'Internal DM',
    'internal-group': 'Internal Group',
  };
  let html = '';
  for (const k of ['mgr', 'dm', 'group', 'internal-dm', 'internal-group']) {
    if (!groups[k].length) continue;
    html += `<div class="channel-group-title">${labels[k]} · ${groups[k].length}</div>`;
    html += `<div class="channel-grid">${groups[k].map(renderChannelCard).join('')}</div>`;
  }
  return html || '<div class="empty">no channels</div>';
}

// 이벤트 타입 → 한글 라벨 + 이모지 매핑.
// raw key 가 어색하거나 (dm_request) 살짝 다듬을 가치 있는 한글 (멤버합류) 모두 보정.
const EVENT_TYPE_META = {
  // 시스템/요청
  'dm_request':       { label: 'DM 요청',     icon: '✉️' },
  '멤버합류':           { label: '새 친구 추가', icon: '🎉' },
  '튜토리얼시작':       { label: '튜토리얼 시작', icon: '🚀' },
  '튜토리얼완료':       { label: '튜토리얼 완료', icon: '🎓' },
  '페르소나생성':       { label: '캐릭터 생성',   icon: '✨' },
  '페르소나추가':       { label: '친구 추가',    icon: '🌱' },
  '톡방생성':           { label: '톡방 생성',    icon: '💬' },
  '단톡방생성':         { label: '단톡방 생성',  icon: '👥' },
  '비밀톡방생성':       { label: '비밀톡방',     icon: '🤫' },
  '그룹생성':           { label: '그룹 생성',    icon: '👥' },
  // 관계
  '관계강화':           { label: '관계 강화',    icon: '💗' },
  '관계갈등':           { label: '관계 갈등',    icon: '⚡' },
  '관계진화':           { label: '관계 진화',    icon: '🌟' },
  '화해':               { label: '화해',         icon: '🤝' },
  '매칭메이킹':         { label: '매칭메이킹',   icon: '🎯' },
  // 일상
  '심야대화':           { label: '심야 대화',    icon: '🌙' },
  '자율대화':           { label: '자율 대화',    icon: '🔄' },
  '회사이벤트':         { label: '회사 이벤트',  icon: '🏢' },
  '작업성과':           { label: '작업 성과',    icon: '🎨' },
  '기념일임박':         { label: '기념일 임박',  icon: '🎁' },
  '감정변화':           { label: '감정 변화',    icon: '💭' },
  '새오너접속':         { label: '오너 복귀',    icon: '👋' },
};

function renderEvent(e) {
  const meta = EVENT_TYPE_META[e.type] || { label: e.type, icon: '◇' };
  const impactCls = {
    '긍정':       'impact-positive',
    '주의':       'impact-warn',
    '마일스톤':   'impact-milestone',
  }[e.impact] || 'impact-neutral';
  const participants = Array.isArray(e.participants) ? e.participants : [];
  const lookupName = (id) => {
    if (id === 'owner' || id === 'jaebin') {
      const cur = window.__GLIMI_LAST_SNAP__ || {};
      return cur.meta?.user_name || (id === 'jaebin' ? '심재빈' : '오너');
    }
    const ag = (window.__GLIMI_LAST_SNAP__?.agents || []).find(a => a.id === id);
    return ag?.name || id;
  };
  // 참여자 칩 — owner 는 핑크, 일반은 회색
  const partsHtml = participants.length
    ? participants.slice(0, 4).map(p => {
        const isOwner = p === 'owner' || p === 'jaebin';
        return `<span class="ev-part ${isOwner ? 'ev-part-owner' : ''}">${esc(lookupName(p))}</span>`;
      }).join('') + (participants.length > 4 ? `<span class="ev-part-more">+${participants.length - 4}</span>` : '')
    : '';
  // 시간 — fmtLocalHMS 가 분 + 초까지 — 이벤트는 더 큰 단위 적합. 상대시간 표기.
  const relTime = (() => {
    if (!e.timestamp) return '';
    try {
      const dt = _parseServerTs(e.timestamp);
      if (!dt || isNaN(dt.getTime())) return e.timestamp.slice(11, 16);
      const secs = (Date.now() - dt.getTime()) / 1000;
      if (secs < 60) return '방금';
      if (secs < 3600) return `${Math.floor(secs / 60)}분 전`;
      if (secs < 86400) return `${Math.floor(secs / 3600)}시간 전`;
      if (secs < 86400 * 7) return `${Math.floor(secs / 86400)}일 전`;
      return `${Math.floor(secs / 86400 / 7)}주 전`;
    } catch { return ''; }
  })();
  return `<div class="event-card ${impactCls}" title="${esc(e.timestamp)}">
    <div class="ev-head">
      <span class="ev-badge">${meta.icon} ${esc(meta.label)}</span>
      ${partsHtml ? `<span class="ev-parts">${partsHtml}</span>` : ''}
      <span class="ev-time">${relTime}</span>
    </div>
    <div class="ev-desc">${esc(e.description)}</div>
  </div>`;
}

// ==== Detail Modal ====
function openModal(emoji, title, body, agent=null) {
  const emojiEl = document.getElementById('d-emoji');
  if (agent && agent.id) {
    // xxl 아바타로 — 56×56 정도. 클릭하면 -full 버전 lightbox
    emojiEl.innerHTML = avatarHtml({...agent, emotion: agent.emotion}, 'xl', { clickOpen: true });
  } else {
    emojiEl.innerHTML = `<span style="font-size:30px">${esc(emoji)}</span>`;
  }
  const titleEl = document.getElementById('d-title');
  titleEl.innerHTML = esc(title.split(' · ')[0]) + (title.includes(' · ') ? `<small>${esc(title.split(' · ').slice(1).join(' · '))}</small>` : '');
  document.getElementById('d-body').innerHTML = body;
  // 에이전트 모달이면 상단에 전체 페이지 링크 표시 (닫기 옆). 그 외 (채널 등) 는 숨김.
  const detailLink = document.getElementById('d-detail-link');
  if (detailLink) {
    if (agent && agent.id) {
      detailLink.href = `/agent/${encodeURIComponent(agent.id)}?community=${encodeURIComponent(COMMUNITY || '')}`;
      detailLink.style.display = '';
    } else {
      detailLink.style.display = 'none';
    }
  }
  document.getElementById('detail-backdrop').classList.add('open');
  // 모달 열린 동안 배경 페이지 스크롤 잠금
  document.documentElement.classList.add('modal-open');
  document.body.classList.add('modal-open');
}
function closeModal() {
  document.getElementById('detail-backdrop').classList.remove('open');
  document.documentElement.classList.remove('modal-open');
  document.body.classList.remove('modal-open');
}
document.getElementById('d-close').addEventListener('click', closeModal);
document.getElementById('detail-backdrop').addEventListener('click', (e) => {
  if (e.target.id === 'detail-backdrop') closeModal();
});

async function openModelPicker(agentId, agentName, currentModel) {
  const catalog = await j('/api/models');
  const models = (catalog && catalog.items) || [];
  if (!models.length) {
    alert('모델 목록을 가져올 수 없어.');
    return;
  }
  // kind 별 그룹핑 — 클라우드/로컬 구분
  const groupOrder = ['cloud', 'local'];
  const groupLabel = {cloud: '☁️ Cloud', local: '🖥️ Local'};
  const byGroup = {};
  models.forEach(m => {
    const g = m.kind || 'cloud';
    (byGroup[g] = byGroup[g] || []).push(m);
  });
  const sections = groupOrder.filter(g => byGroup[g] && byGroup[g].length).map(g => {
    const cards = byGroup[g].map(m => {
      const checked = m.id === currentModel ? 'checked' : '';
      const icon = m.icon || (m.kind === 'local' ? '🖥️' : '☁️');
      return `<label style="display:flex;gap:10px;padding:10px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;cursor:pointer;align-items:center">
        <input type="radio" name="model-pick" value="${esc(m.id)}" ${checked}>
        <span style="font-size:18px">${icon}</span>
        <div style="flex:1">
          <div style="font-weight:600">${esc(m.label)}</div>
          <div style="font-size:11px;color:var(--text-dim)">${esc(m.id)} · ${esc(m.provider || '')} · ${esc(m.tier || '')}</div>
        </div>
      </label>`;
    }).join('');
    return `<div style="margin-bottom:10px"><div style="font-size:11.5px;color:var(--text-dim);margin-bottom:6px;font-weight:600">${groupLabel[g] || g}</div>${cards}</div>`;
  }).join('');
  const lines = sections;
  const content = `
    <div style="font-size:13px;color:var(--text-dim);margin-bottom:12px">
      <b>${esc(agentName)}</b> 의 실효 모델을 교체합니다.<br>
      대화 이력·메모리는 DB 기반이라 자동 보존됩니다. 다음 턴부터 반영 (재시작 불필요).
    </div>
    <form id="model-pick-form">${lines}</form>
    <div style="display:flex;gap:8px;margin-top:14px;justify-content:flex-end">
      <button class="act-btn" onclick="event.stopPropagation(); resetAgentModel('${esc(agentId)}')">기본값으로 (Override 해제)</button>
      <button class="act-btn primary" onclick="event.stopPropagation(); applyAgentModel('${esc(agentId)}')">적용</button>
    </div>
  `;
  openModal('◆', `모델 선택 — ${esc(agentName)}`, content);
}

async function applyAgentModel(agentId) {
  const form = document.getElementById('model-pick-form');
  if (!form) return;
  const picked = form.querySelector('input[name="model-pick"]:checked');
  if (!picked) { alert('모델 선택 필요'); return; }
  const r = await postJson(q('/api/action/set_agent_model'), {agent_id: agentId, model: picked.value});
  if (r && r.ok) {
    closeModal();
    toast(`모델 변경 완료: ${picked.value}`, 'ok');
    // agent 모달 재오픈해서 반영 확인
    setTimeout(() => openAgent(agentId), 400);
  } else {
    toast(`실패: ${r?.error || '알 수 없음'}`, 'err');
  }
}

async function resetAgentModel(agentId) {
  const r = await postJson(q('/api/action/set_agent_model'), {agent_id: agentId, model: ''});
  if (r && r.ok) {
    closeModal();
    toast('Override 해제됨 (type 기본값 사용)', 'ok');
    setTimeout(() => openAgent(agentId), 400);
  } else {
    toast(`실패: ${r?.error || '알 수 없음'}`, 'err');
  }
}

// ── Elastic Memory — 커뮤니티별 컨텍스트(num_ctx) 사양 조절 ──
const _EM_SEG_COLORS = {
  system: 'var(--accent)', memory: '#1d9e75', recent: '#c98a1a',
  output: 'var(--text-faint)', safety: 'var(--border)',
};
function _emSectionLabel(t) {
  return `<div style="font-size:10.5px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;color:var(--text-faint);margin:0 0 8px">${t}</div>`;
}
function _emBar(b) {
  const segs = b.segments || [];
  const total = segs.reduce((s, x) => s + x.tokens, 0) || 1;
  const fills = segs.filter(s => s.tokens > 0).map(s =>
    `<div title="${esc(s.label_ko)} · ${s.tokens.toLocaleString()} tok" style="width:${(s.tokens/total*100).toFixed(1)}%;background:${_EM_SEG_COLORS[s.key]||'var(--border)'}"></div>`).join('');
  const legend = segs.filter(s => s.tokens > 0).map(s =>
    `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--text-dim)">
       <span style="width:9px;height:9px;border-radius:2px;background:${_EM_SEG_COLORS[s.key]||'var(--border)'}"></span>
       ${esc(s.label_ko)} <span style="font-variant-numeric:tabular-nums;color:var(--text-faint)">${s.tokens.toLocaleString()}</span></span>`).join('');
  const modelShort = (b.model||'').split('/').pop();
  return `<div style="margin-bottom:13px">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px">
      <span style="font-size:12.5px;font-weight:500">${esc(b.agent_label_ko)}</span>
      <span style="font-family:var(--font-mono);font-size:10.5px;color:var(--text-dim)">${esc(modelShort)} · ${b.num_ctx.toLocaleString()} tok</span>
    </div>
    <div style="display:flex;height:22px;border-radius:5px;overflow:hidden;border:1px solid var(--border)">${fills}</div>
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:6px">${legend}</div>
  </div>`;
}
function _emRender(d) {
  const specs = d.specs || {};
  const accelLabel = {nvidia_vram: 'GPU VRAM', apple_unified: '통합 메모리', cpu_or_unknown: '시스템 RAM'}[specs.accel] || '메모리';
  const levelLabel = {compact: 'Compact', standard: 'Standard', full: 'Full'}[d.detail_level] || d.detail_level;

  const modelChips = (d.models || []).map(m =>
    `<div style="display:flex;align-items:baseline;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-soft)">
      <span style="font-family:var(--font-mono);font-size:11.5px;color:var(--text)">${esc((m.model||'').split('/').pop())}</span>
      <span style="font-size:11px;color:var(--text-dim)">${esc((m.roles_ko||[]).join(' · '))}</span>
    </div>`).join('');

  const bars = (d.breakdown || []).map(_emBar).join('');

  const cards = (d.tiers || []).map(t => {
    const cur = t.key === d.current_tier;
    const rec = t.key === d.recommended_tier;
    return `<label style="display:flex;gap:10px;padding:10px 11px;border:${cur ? '2px solid var(--accent)' : '1px solid var(--border)'};border-radius:9px;margin-bottom:6px;cursor:pointer;align-items:center;background:${cur ? 'var(--accent-soft, transparent)' : 'transparent'}">
      <input type="radio" name="em-pick" value="${t.num_ctx}" ${cur ? 'checked' : ''}>
      <div style="font-size:17px;font-weight:600;width:22px;text-align:center;color:${cur ? 'var(--accent)' : 'var(--text-dim)'}">${esc(t.label_ko)}</div>
      <div style="flex:1">
        <div style="font-size:13px;font-weight:500">${esc(t.label_en)} · <span style="font-family:var(--font-mono);font-size:12px">${t.num_ctx.toLocaleString()}</span> tok ${rec ? '<span style="font-size:10px;color:var(--ok);font-weight:500">· 권장</span>' : ''}</div>
        <div style="font-size:11px;color:var(--text-dim)">${esc(t.note_ko)}</div>
      </div>
    </label>`;
  }).join('');

  return `
    <div style="font-size:12px;color:var(--text-dim);margin-bottom:14px;line-height:1.65">
      주입 기억과 시스템 프롬프트를 컨텍스트 크기에 맞춰 탄력 조절합니다. 크면 기억을 더 풍부하게,
      작으면 절약 (로컬 모델 · 봇 재기동 시 반영).
    </div>

    ${_emSectionLabel('모델 구성')}
    <div style="background:var(--panel-2);border-radius:8px;padding:4px 12px;margin-bottom:16px">${modelChips || '<div style="padding:8px 0;font-size:12px;color:var(--text-dim)">로컬 백엔드 아님</div>'}</div>

    ${_emSectionLabel(`컨텍스트 점유 · ${esc(levelLabel)} 프롬프트`)}
    ${bars || ''}

    ${_emSectionLabel('감지 사양 · 권장')}
    <div style="background:var(--panel-2);border-radius:8px;padding:9px 12px;margin-bottom:14px;font-size:12px">
      <div style="display:flex;justify-content:space-between"><span style="color:var(--text-dim)">감지된 사양</span>
        <span><b>${(specs.usable_gb||0)}GB</b> ${esc(accelLabel)} <span style="color:var(--text-faint)">(${esc(specs.platform||'?')})</span></span></div>
      <div style="display:flex;justify-content:space-between;margin-top:4px"><span style="color:var(--text-dim)">권장</span>
        <span>${esc(d.recommended_reason_ko||'')}</span></div>
    </div>

    ${_emSectionLabel('컨텍스트 크기')}
    <form id="em-form">${cards}</form>
    <div style="display:flex;gap:8px;margin-top:12px;justify-content:flex-end">
      <button class="act-btn" onclick="event.stopPropagation(); emApply(true)">사양 감지 → 권장값</button>
      <button class="act-btn primary" onclick="event.stopPropagation(); emApply(false)">적용</button>
    </div>`;
}

async function openElasticMemory() {
  if (!COMMUNITY) { toast('커뮤니티를 먼저 선택해줘', 'err'); return; }
  const d = await j(q('/api/elastic-memory'));
  if (!d || d.error) { toast(`불러오기 실패: ${d?.error || '알 수 없음'}`, 'err'); return; }
  openModal('🧠', 'Elastic Memory · 컨텍스트 사양', _emRender(d));
}

async function emApply(useRecommended) {
  const body = {community: COMMUNITY};
  if (useRecommended) {
    body.use_recommended = true;
  } else {
    const form = document.getElementById('em-form');
    const picked = form && form.querySelector('input[name="em-pick"]:checked');
    if (!picked) { toast('값 선택 필요', 'err'); return; }
    body.num_ctx = parseInt(picked.value, 10);
  }
  const r = await postJson('/api/elastic-memory/set', body);
  if (r && r.ok) {
    toast(`컨텍스트 ${r.saved_num_ctx.toLocaleString()} tok 저장 — 봇 재기동 시 반영`, 'ok');
    document.getElementById('d-body').innerHTML = _emRender(r);
  } else {
    toast(`실패: ${r?.error || '알 수 없음'}`, 'err');
  }
}

async function openAgent(id) {
  // 모달 = 요약 상단 (항상 펼침) + 상세 섹션 4개 (details/summary 접힘).
  // 풀페이지 링크는 하단 유지. 세로 밀도는 max-height: 100vh-48px (panel) 안에서 overflow.
  const d = await j(q(`/api/agent?id=${encodeURIComponent(id)}`));
  if (!d || d.error) { openModal('⚠', 'Error', `<div class="empty">${esc(d?.error || 'failed to load')}</div>`); return; }

  // ── Status chip (실시간 상태) ──────────
  const isOffline = document.body.classList.contains('offline');
  let statusHtml;
  if (isOffline) {
    statusHtml = '<span style="color:var(--text-dim)">○ Inactive (서버 오프라인)</span>';
  } else if (d.thinking) {
    statusHtml = '<span style="color:var(--thinking)">🧠 Thinking</span>';
  } else if (d.speaking) {
    statusHtml = '<span style="color:var(--speaking)">💬 Speaking</span>';
  } else if (d.status === 'active') {
    statusHtml = '<span style="color:var(--ok)">● Active</span>';
  } else {
    statusHtml = `<span style="color:var(--text-dim)">○ ${esc(d.status)}</span>`;
  }

  // ── Model chip (요약 — 변경 버튼은 전체 페이지 또는 여기서도 유지) ──
  let modelHtml = '';
  if (d.model) {
    const canPickModel = d.type === 'persona';
    modelHtml = renderModelChips(d) + (
      canPickModel
        ? `<button class="act-btn small" style="margin-left:8px" onclick="event.stopPropagation(); openModelPicker('${esc(d.id)}','${esc(d.name)}','${esc(d.model || '')}')">변경</button>`
        : `<small style="margin-left:8px;color:var(--text-faint)">(고정)</small>`
    );
  }

  // ── 관계 top 3 (친밀도 내림차순) — 요약용 ──
  // 친밀도 스케일: 0 원수 / 1-19 적대 / 20-39 어색 / 40-59 친구 / 60-79 친한 친구 / 80-99 절친 / 100 연인
  const intimacyBand = (n) => {
    if (n >= 100) return { label: '연인', cls: 'b-lover', emoji: '💖' };
    if (n >= 80) return { label: '절친', cls: 'b-best', emoji: '💞' };
    if (n >= 60) return { label: '친한 친구', cls: 'b-close', emoji: '🤝' };
    if (n >= 40) return { label: '친구', cls: 'b-friend', emoji: '🙂' };
    if (n >= 20) return { label: '어색', cls: 'b-awkward', emoji: '😶' };
    if (n >= 1) return { label: '적대', cls: 'b-hostile', emoji: '😠' };
    return { label: '원수', cls: 'b-enemy', emoji: '🔥' };
  };
  // 관계 타입 이모지 — 자유 텍스트지만 자주 등장하는 키워드 매핑
  const relTypeEmoji = (t) => {
    if (!t) return '';
    if (/매니저|관리/.test(t)) return '🛡️';
    if (/크리에이터|creator/.test(t)) return '🎨';
    if (/개발/.test(t)) return '🛠️';
    if (/연인|애인/.test(t)) return '💖';
    if (/가족|엄마|아빠|형|누나|언니|오빠|동생/.test(t)) return '👨‍👩‍👧';
    if (/친구/.test(t)) return '🙂';
    if (/라이벌/.test(t)) return '⚔️';
    if (/멘토|선생/.test(t)) return '🎓';
    if (/짝사랑/.test(t)) return '💗';
    if (/원수|적/.test(t)) return '🔥';
    return '·';
  };
  const relsSorted = (d.relationships || []).slice().sort((a, b) => (b.intimacy || 0) - (a.intimacy || 0));
  const relsTop = relsSorted.slice(0, 3);
  const renderRelRow = (r) => {
    const pct = Math.min(100, r.intimacy);
    const band = intimacyBand(r.intimacy || 0);
    const tEmoji = relTypeEmoji(r.type);
    return `<div class="rel-row">
      <span class="rname" title="${esc(r.other_name)}">${esc(r.other_name)}</span>
      <div class="intimacy-bar-v2 band-${band.cls}" title="친밀도 ${r.intimacy}/100 (0=원수 100=연인)">
        <div class="intimacy-bar-fill" style="width:${pct}%"></div>
        <div class="intimacy-bar-text">
          <span class="rel-type">${tEmoji} ${esc(r.type || '—')}</span>
          <span class="rel-sep">·</span>
          <span class="rel-band">${band.emoji} ${band.label}</span>
          <span class="rel-score">${r.intimacy}/100</span>
        </div>
      </div>
      ${r.dynamics ? `<span class="dynamics" title="${esc(r.dynamics)}">${esc(r.dynamics)}</span>` : ''}
    </div>`;
  };
  const relsTopHtml = relsTop.map(renderRelRow).join('');
  const relsAllHtml = relsSorted.map(renderRelRow).join('');

  // ── 최근 활동 1줄 (요약) ──────────────
  const lastMsg = (d.primary_chat || []).slice(-1)[0];
  const recentLine = lastMsg
    ? `<div style="display:flex;gap:8px;align-items:baseline;font-size:12.5px;color:var(--text-dim)">
        <span style="color:var(--text-faint)">#${esc(lastMsg.channel || d.primary_channel || '')}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(lastMsg.message)}">${esc((lastMsg.message || '').slice(0, 120))}</span>
        <span style="color:var(--text-faint);font-size:11px">${esc(_fmtMsgTime(lastMsg.timestamp))}</span>
      </div>`
    : '<div style="color:var(--text-faint);font-size:12px">최근 활동 없음</div>';

  // ── 메모리 섹션 (pinned + by channel + facts + relationship_history) ──
  const TYPE_LABEL = {
    event: {label: '사건', icon: '🎬'},
    fact: {label: '사실', icon: '💡'},
    emotion: {label: '감정', icon: '💓'},
    relationship: {label: '관계', icon: '🤝'},
  };
  const renderMemItem = (m, opts = {}) => {
    const t = m.mem_type ? TYPE_LABEL[m.mem_type] : null;
    const typeBadge = t ? `<span class="mem-type-badge" title="유형">${t.icon} ${t.label}</span>` : '';
    const imp = m.importance ? `<span class="mem-imp" title="중요도 ${m.importance}/10">${m.importance}</span>` : '';
    const pin = m.is_pinned ? '<span class="mem-pin" title="고정됨">📌</span>' : '';
    const ents = (m.related_entities && m.related_entities.length)
      ? `<span class="mem-ents" title="관련 대상">${m.related_entities.map(e => esc(e)).join(' · ')}</span>` : '';
    const ch = opts.showChannel && m.channel ? `<span class="mem-ch">${esc(m.channel)}</span>` : '';
    return `<div class="mem-item" data-mem-id="${m.id || ''}">
      ${pin}${typeBadge}${imp}
      <span class="mcontent">${esc(m.content)}</span>
      ${ents}${ch}
      <span class="mts">${esc(fmtLocalMonthDayHM(m.created_at))}</span>
    </div>`;
  };
  const LAYER_LABEL = {
    1: {name: '최근', icon: '📖', desc: '최근 몇 분~몇 시간 요약'},
    2: {name: '중기', icon: '📚', desc: '하루 분량 묶음 요약'},
    3: {name: '장기', icon: '🗂', desc: '주/월 단위 큰 흐름'},
  };
  let memHtml = '';
  let memCount = 0;
  if ((d.pinned_memories || []).length) {
    memCount += d.pinned_memories.length;
    memHtml += `<div class="mem-block mem-pinned-block">
      <h5>📌 고정된 기억 <span class="mem-count">(${d.pinned_memories.length})</span>
        <span class="mem-sub">항상 떠올리는 기억</span></h5>
      ${d.pinned_memories.map(m => renderMemItem(m, {showChannel: true})).join('')}
    </div>`;
  }
  for (const [ch, mems] of Object.entries(d.memories_by_channel || {})) {
    memCount += mems.length;
    const byLevel = {3: [], 2: [], 1: []};
    mems.forEach(m => { (byLevel[m.level] || byLevel[1]).push(m); });
    const anyLevels = [3, 2, 1].filter(l => byLevel[l].length);
    if (!anyLevels.length) continue;
    memHtml += `<div class="mem-block">
      <h5><span class="ch-icon">${chIcon(ch)}</span> ${esc(ch)} <span class="mem-count">(${mems.length})</span></h5>
      ${anyLevels.map(l => {
        const L = LAYER_LABEL[l];
        return `<div class="mem-lvl-group">
          <div class="mem-lvl-label" title="${L.desc}">${L.icon} ${L.name} <span class="mem-count">(${byLevel[l].length})</span></div>
          ${byLevel[l].map(renderMemItem).join('')}
        </div>`;
      }).join('')}
    </div>`;
  }
  if ((d.agent_facts || []).length) {
    memCount += d.agent_facts.length;
    const bySubject = {};
    (d.agent_facts || []).forEach(f => {
      if (!bySubject[f.subject]) bySubject[f.subject] = [];
      bySubject[f.subject].push(f);
    });
    memHtml += `<div class="mem-block mem-facts-group">
      <h5>💡 알고 있는 사실 <span class="mem-count">(${d.agent_facts.length})</span>
        <span class="mem-sub">대상별 구조화된 지식</span></h5>`;
    memHtml += Object.entries(bySubject).map(([subject, facts]) =>
      `<div class="mem-subject-block">
        <div class="mem-subject-label">${esc(subject)} <span class="mem-count">(${facts.length})</span></div>
        ${facts.map(f => `<div class="mem-item">
          <span class="mem-predicate">${esc(f.predicate)}</span>
          <span class="mcontent">${esc(f.object)}</span>
          ${f.importance >= 8 ? '<span class="mem-pin" title="중요">⭐</span>' : ''}
          <span class="mts">${esc(fmtLocalMonthDayHM(f.created_at))}</span>
        </div>`).join('')}
      </div>`
    ).join('');
    memHtml += '</div>';
  }
  if ((d.relationship_history || []).length) {
    memCount += d.relationship_history.length;
    memHtml += `<div class="mem-block">
      <h5>📈 관계 변화 <span class="mem-count">(${d.relationship_history.length})</span></h5>
      ${d.relationship_history.slice(0, 10).map(h => `<div class="mem-item">
        <span class="mem-predicate">${esc(h.delta_type || '?')}</span>
        <span class="mcontent">${esc(h.from_state || '?')} → ${esc(h.to_state || '?')}${h.reason ? ' · ' + esc(h.reason) : ''}</span>
        <span class="mts">${esc(fmtLocalMonthDayHM(h.created_at))}</span>
      </div>`).join('')}
    </div>`;
  }

  // ── 추론 로그 ───────────────────────────
  const thinkingCount = (d.thinking_logs || []).length;
  const thinkingHtml = (d.thinking_logs || []).map(l =>
    `<div class="logline" style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-dim);padding:2px 0">${esc(l)}</div>`
  ).join('');

  // ── 최근 대화 ───────────────────────────
  const chatCount = (d.primary_chat || []).length;
  const chatHtml = (d.primary_chat || []).map(m => renderMessage({...m, channel: m.channel || d.primary_channel})).join('');

  // 전체 보기 URL 은 이제 openModal 이 header 링크에 자동 세팅 (이 함수에선 body 구성만).
  // 감정 바 — emoji+라벨이 바 안에, 강도가 fill 너비로. 점수 인상 회피 + 한눈 가독.
  const emotionLine = d.emotion
    ? (() => {
        const pct = Math.min(100, (d.intensity || 0) * 10);
        return `<div class="emotion-bar" title="강도 ${esc(String(d.intensity ?? '?'))}/10">
          <div class="emotion-bar-fill" style="width:${pct}%"></div>
          <div class="emotion-bar-text">${esc(d.emoji || '')} ${esc(d.emotion)}</div>
        </div>`;
      })()
    : '';

  // details/summary 공통 스타일 (인라인 — 신규 CSS 최소화)
  const sumStyle = 'cursor:pointer;list-style:none;padding:10px 14px;margin:-14px -16px;border-radius:10px;font-size:11px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:1.2px;display:flex;align-items:center;gap:8px';
  const secInner = 'margin-top:12px';

  // ── 프로필 정보 (항상 펼침 — 에이전트의 본질 정보) ──
  const joinList = (arr) => (arr || []).map(esc).join(', ');
  const profileRows = [
    d.age ? ['나이', `${esc(String(d.age))}${d.birth_year ? ` <span style="color:var(--text-faint)">(${esc(String(d.birth_year))})</span>` : ''}`] : null,
    d.gender ? ['성별', esc(d.gender)] : null,
    d.mbti ? ['MBTI', esc(d.mbti)] : null,
    d.enneagram ? ['에니어그램', esc(d.enneagram)] : null,
    (d.traits && d.traits.length) ? ['성격', joinList(d.traits)] : null,
    (d.likes && d.likes.length) ? ['좋아함', joinList(d.likes)] : null,
    (d.dislikes && d.dislikes.length) ? ['싫어함', joinList(d.dislikes)] : null,
    d.hobby ? ['취미', esc(d.hobby)] : null,
    d.values ? ['가치관', esc(d.values)] : null,
    d.occupation ? ['직업', esc(d.occupation)] : null,
    d.routine ? ['일상', esc(d.routine)] : null,
    (d.frequent_places && d.frequent_places.length) ? ['자주 가는 곳', joinList(d.frequent_places)] : null,
    d.appearance_summary ? ['외모', esc(d.appearance_summary)] : null,
    d.fashion_style ? ['패션', esc(d.fashion_style)] : null,
    d.speech_style ? ['말투', esc(d.speech_style)] : null,
    (d.signature_expressions && d.signature_expressions.length) ? ['자주 쓰는 표현', joinList(d.signature_expressions)] : null,
    d.background ? ['배경', esc(d.background)] : null,
  ].filter(Boolean);
  const profileHtml = profileRows.length
    ? `<dl class="kv">${profileRows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`
    : '<div style="color:var(--text-faint);font-size:12px">프로필 정보 없음</div>';

  // 관계 오너 정보
  const relOwner = d.relationship_to_owner || {};
  const relOwnerRows = [
    relOwner.type ? ['오너와의 관계', esc(relOwner.type)] : null,
    relOwner.pet_name ? ['호칭', esc(relOwner.pet_name)] : null,
    relOwner.dynamics ? ['dynamics', esc(relOwner.dynamics)] : null,
  ].filter(Boolean);
  const relOwnerHtml = relOwnerRows.length
    ? `<dl class="kv">${relOwnerRows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`
    : '';

  // ── Supervisor 이벤트 히스토리 ──
  // is_supervisor 면 활동 로그 섹션을 모달 상단에 노출 (감시 횟수 + 최근 액션).
  let supEventsHtml = '';
  if (d.is_supervisor) {
    const events = d.supervisor_events || [];
    const totalCount = d.supervisor_event_count || events.length;
    if (events.length) {
      const fmtTs = (iso) => {
        try {
          const dt = _parseServerTs(iso);
          if (!dt || isNaN(dt.getTime())) return iso;
          const secs = (Date.now() - dt.getTime()) / 1000;
          if (secs < 60) return `${Math.floor(secs)}s ago`;
          if (secs < 3600) return `${Math.floor(secs/60)}m ago`;
          if (secs < 86400) return `${Math.floor(secs/3600)}h ago`;
          return `${Math.floor(secs/86400)}d ago`;
        } catch { return iso; }
      };
      const evRows = events.slice(0, 30).map(ev => {
        const outcomeColor = ev.outcome === 'failed' ? '#ef4444' : (ev.outcome === 'skipped' ? 'var(--text-faint)' : 'var(--ok,#10b981)');
        const targets = (ev.targets || []).map(t => esc(t)).join(', ');
        return `<div style="padding:6px 0;border-bottom:1px dashed var(--border-soft);font-size:12px">
          <div style="display:flex;gap:8px;align-items:baseline">
            <span style="color:${outcomeColor};font-weight:600;font-family:monospace;font-size:11px">${esc(ev.action)}</span>
            <span style="color:var(--text-dim);flex:1">${esc(ev.summary || '')}</span>
            <span style="color:var(--text-faint);font-size:10px">${fmtTs(ev.ts)}</span>
          </div>
          ${targets ? `<div style="color:var(--text-faint);font-size:10.5px;margin-top:2px">→ ${targets}</div>` : ''}
        </div>`;
      }).join('');
      supEventsHtml = `<div class="detail-section">
        <h4>📋 감시 활동 <span class="mem-count">(${totalCount} · 24h)</span></h4>
        <div style="max-height:280px;overflow-y:auto">${evRows}</div>
      </div>`;
    } else {
      supEventsHtml = `<div class="detail-section">
        <h4>📋 감시 활동</h4>
        <div class="empty" style="font-size:12px">최근 24시간 내 기록된 개입 없음 — 조용히 감시 중</div>
      </div>`;
    }
  }

  const body = `
    ${supEventsHtml}
    <div class="detail-section" style="margin-top:0">
      <h4>📊 상태</h4>
      <dl class="kv">
        ${emotionLine ? `<dt>${t('f_emotion')}</dt><dd>${emotionLine}</dd>` : ''}
        <dt>${t('f_status')}</dt><dd>${statusHtml}</dd>
        ${modelHtml ? `<dt>${t('f_model')}</dt><dd>${modelHtml}</dd>` : ''}
      </dl>
    </div>
    <div class="detail-section">
      <h4>👤 프로필</h4>
      ${profileHtml}
      ${relOwnerHtml ? `<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">${relOwnerHtml}</div>` : ''}
    </div>
    ${relsTopHtml ? `<div class="detail-section"><h4>🤝 관계 · Top ${relsTop.length}</h4>${relsTopHtml}</div>` : ''}
    <div class="detail-section">
      <h4>💬 최근 활동</h4>
      ${recentLine}
    </div>
    ${memHtml ? `<details class="detail-section" style="padding:14px 16px">
      <summary style="${sumStyle}"><span>🧠 메모리 <span class="mem-count" style="text-transform:none;letter-spacing:0">(${memCount})</span></span><span style="margin-left:auto;color:var(--text-faint);font-weight:400;text-transform:none;letter-spacing:0;font-size:10px">클릭해서 펼치기</span></summary>
      <div style="${secInner}">${memHtml}</div>
    </details>` : ''}
    ${relsAllHtml && relsSorted.length > 3 ? `<details class="detail-section" style="padding:14px 16px">
      <summary style="${sumStyle}"><span>🤝 관계 전체 <span class="mem-count" style="text-transform:none;letter-spacing:0">(${relsSorted.length})</span></span><span style="margin-left:auto;color:var(--text-faint);font-weight:400;text-transform:none;letter-spacing:0;font-size:10px">클릭해서 펼치기</span></summary>
      <div style="${secInner}">${relsAllHtml}</div>
    </details>` : ''}
    ${thinkingHtml ? `<details class="detail-section" style="padding:14px 16px">
      <summary style="${sumStyle}"><span>💭 추론 로그 <span class="mem-count" style="text-transform:none;letter-spacing:0">(${thinkingCount})</span></span><span style="margin-left:auto;color:var(--text-faint);font-weight:400;text-transform:none;letter-spacing:0;font-size:10px">클릭해서 펼치기</span></summary>
      <div style="${secInner}">${thinkingHtml}</div>
    </details>` : ''}
    ${chatHtml ? `<details class="detail-section" style="padding:14px 16px">
      <summary style="${sumStyle}"><span>💬 최근 대화 · ${esc(d.primary_channel || '')} <span class="mem-count" style="text-transform:none;letter-spacing:0">(${chatCount})</span></span><span style="margin-left:auto;color:var(--text-faint);font-weight:400;text-transform:none;letter-spacing:0;font-size:10px">클릭해서 펼치기</span></summary>
      <div class="msg-list" style="${secInner}">${chatHtml}</div>
    </details>` : ''}
  `;
  openModal(d.emoji, d.name + ' · ' + d.type, body, d);
}

async function openChannel(name) {
  const d = await j(q(`/api/channel?name=${encodeURIComponent(name)}`));
  if (!d) { openModal('⚠', 'Error', '<div class="empty">failed to load</div>'); return; }
  const parts = (d.participants || []).map(p => `<span class="pill neutral">${esc(p.name)}${p.type ? ' · ' + esc(p.type) : ''}</span>`).join(' ');
  const msgs = (d.messages || []).map(m => renderMessageWithActions(m, name)).join('');
  const protected_ch = name.startsWith('mgr-') || name.startsWith('dm-');
  const actions = `
    <div class="detail-section">
      <h4>Actions</h4>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="act-btn danger small" onclick="doChannelClear('${esc(name)}')">🧹 메시지 전체 삭제 (DB만)</button>
        ${!protected_ch ? `<button class="act-btn danger small" onclick="doChannelDelete('${esc(name)}')">🗑 채널 삭제</button>` : ''}
      </div>
    </div>`;
  const body = `
    <div class="detail-section">
      <h4>Participants · ${d.participants.length}</h4>
      <div style="display:flex;gap:6px;flex-wrap:wrap">${parts || '<span style="color:var(--text-faint)">none</span>'}</div>
    </div>
    ${actions}
    <div class="detail-section">
      <h4>All Messages · ${d.message_count}</h4>
      <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px">각 메시지 우측 🗑 버튼으로 개별 trash 이동</div>
      <div class="msg-list" id="ch-messages-${esc(name)}">${msgs || '<div class="empty">no messages</div>'}</div>
    </div>`;
  openModal(chIcon(name), '#' + name, body);
}

function renderMessageWithActions(m, channelName) {
  return `<div class="msg ${roleClass(m)}" data-msg-id="${m.id || ''}" style="position:relative">
    ${miniAvatarHtml(m.speaker_id, m.is_user, m.speaker)}
    <div class="msg-body" style="padding-right:28px">
      <div class="head">
        <span class="who">${esc(m.speaker)}</span>
        <span class="ch" onclick="event.stopPropagation(); openChannel('${esc(m.channel)}')">#${esc(m.channel)}</span>
        <span class="ts" title="${esc(m.timestamp || '')}">${esc(_fmtMsgTime(m.timestamp))}</span>
      </div>
      <div class="text">${esc(m.message)}</div>
    </div>
    ${m.id ? `<button class="msg-del-btn" onclick="event.stopPropagation(); doTrashMessage('${esc(channelName)}', ${m.id}, this)" title="이 메시지 Trash로 이동">🗑</button>` : ''}
  </div>`;
}

async function doTrashMessage(channel, msgId, btn) {
  if (!confirm('이 메시지를 trash로 옮길까? (복구 가능)')) return;
  const r = await postJson(q('/api/action/trash_message'), {channel, message_id: msgId});
  if (r.error) return toast(r.message || r.error, 'err');
  toast('trash로 이동됨', 'ok');
  // 해당 메시지 카드 fade out + remove
  const card = btn?.closest('.msg');
  if (card) {
    card.style.transition = 'opacity 0.3s, transform 0.3s';
    card.style.opacity = '0';
    card.style.transform = 'translateX(20px)';
    setTimeout(() => card.remove(), 300);
  }
}

// ==== Mutation actions ====
function toast(msg, variant='ok', ms=3000) {
  const el = document.getElementById('toast');
  el.className = `toast show ${variant}`;
  el.textContent = msg;
  setTimeout(() => { el.classList.remove('show'); }, ms);
}

async function postJson(url, body, extraOpts) {
  // extraOpts.signal 로 AbortController 지원 (sync 모달 취소용).
  // extraOpts.rethrowAbort true 시 AbortError 그대로 throw (catch 쪽에서 처리).
  const opts = {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {}),
  };
  if (extraOpts && extraOpts.signal) opts.signal = extraOpts.signal;
  try {
    const r = await fetch(url, opts);
    return await r.json();
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    return {error: 'fetch_failed', message: String(e)};
  }
}

async function waitFor(cond, msEach=500, maxTries=60) {
  for (let i = 0; i < maxTries; i++) {
    if (await cond()) return true;
    await new Promise(r => setTimeout(r, msEach));
  }
  return false;
}

async function isBotRunning() {
  const d = await j('/api/communities');
  if (!d) return false;
  const item = (d.items || []).find(c => c.id === (COMMUNITY || d.active));
  return !!(item && item.running);
}

let _syncAbortCtrl = null;
let _syncInProgress = false;

function openSyncModal(title, cancellable) {
  document.getElementById('sync-modal').style.display = 'flex';
  document.getElementById('sync-modal-title').textContent = title;
  document.getElementById('sync-modal-subtitle').textContent = '다른 탭·버튼 이용 불가';
  document.getElementById('sync-modal-spinner').style.display = 'block';
  document.getElementById('sync-modal-cancel').style.display = cancellable ? 'inline-block' : 'none';
  document.getElementById('sync-modal-close').style.display = 'none';
  document.getElementById('sync-modal-log').textContent = '';
  _syncInProgress = true;
}

function finishSyncModal(success) {
  document.getElementById('sync-modal-spinner').style.display = 'none';
  document.getElementById('sync-modal-cancel').style.display = 'none';
  document.getElementById('sync-modal-close').style.display = 'inline-block';
  document.getElementById('sync-modal-subtitle').textContent = success ? '완료 ✓' : '중단됨';
  _syncInProgress = false;
}

function closeSyncModal() {
  if (_syncInProgress) return;  // 진행 중엔 강제 닫기 금지
  document.getElementById('sync-modal').style.display = 'none';
}

function cancelSyncAction() {
  if (_syncAbortCtrl) {
    _syncAbortCtrl.abort();
    appendSyncLog('\n⏸ 취소 요청됨...');
  }
}

function appendSyncLog(s) {
  const log = document.getElementById('sync-modal-log');
  log.textContent += s + '\n';
  log.scrollTop = log.scrollHeight;
}

// Scan 결과 + 선택 상태 — 탭 재렌더에도 살아남음
let _lastScanResult = null;   // {counts, db_counts, total, channels_scanned}
let _syncSelectedChannels = new Set();

// 메시지 drift 무시 채널 (백엔드 actions.py 의 MSG_SYNC_EXCLUDED 와 일치).
// 채널 존재 여부 (missing/orphan) 는 그대로 체크 — drift 만 스킵.
const MSG_SYNC_EXCLUDED = new Set(['mgr-system-log']);

function _chDiffInfo(dbCount, dcCount) {
  const diff = dbCount - dcCount;
  if (diff > 0) return { cls: 'diff-up', label: `⬆ ${diff}건 Discord 누락 → 복원` };
  if (diff < 0) return { cls: 'diff-down', label: `⬇ ${-diff}건 Discord 초과 → 삭제` };
  return { cls: 'diff-ok', label: '✓ 동기화됨' };
}

function renderScanTable() {
  const host = document.getElementById('scan-result');
  if (!host) return;
  if (!_lastScanResult) {
    host.innerHTML = '';
    return;
  }
  const dc = _lastScanResult.counts || {};
  const dbC = _lastScanResult.db_counts || {};
  const allChs = new Set([...Object.keys(dc), ...Object.keys(dbC)]);
  // 같은 tolerance 를 backend _analyze_damage 와 일치시킴 — startup prep 의 damage 판정과
  // sync 탭의 "필요" 판정이 같도록. 절대 ≤5 AND 상대 ≤5% drift 는 split mismatch 등 비파괴.
  const TOL_ABS = 5;
  const TOL_REL = 0.05;
  const isSignificant = (db, dcCount) => {
    const a = Math.abs(db - dcCount);
    if (a === 0) return false;
    const denom = Math.max(db, dcCount, 1);
    return a > TOL_ABS && (a / denom) > TOL_REL;
  };
  // MSG_SYNC_EXCLUDED 채널은 테이블엔 보이지만 체크박스 비활성 + 딤처리 — 존재는 알리되
  // 유저가 싱크 대상으로 실수 선택 못하게.
  const rows = [...allChs].map(ch => {
    const dbCount = dbC[ch] || 0;
    const dcCount = dc[ch] || 0;
    const diff = dbCount - dcCount;
    return {
      ch,
      db: dbCount,
      dc: dcCount,
      diff,
      needsSync: !MSG_SYNC_EXCLUDED.has(ch) && isSignificant(dbCount, dcCount),
      isMinor: !MSG_SYNC_EXCLUDED.has(ch) && diff !== 0 && !isSignificant(dbCount, dcCount),
      excluded: MSG_SYNC_EXCLUDED.has(ch),
    };
  });
  // 제외 채널은 가장 아래로, 나머지는 needsSync 우선 → minor drift → diff 큰 순
  rows.sort((a, b) => {
    if (a.excluded !== b.excluded) return a.excluded ? 1 : -1;
    const needA = a.needsSync ? 0 : (a.isMinor ? 1 : 2);
    const needB = b.needsSync ? 0 : (b.isMinor ? 1 : 2);
    if (needA !== needB) return needA - needB;
    return Math.abs(b.diff) - Math.abs(a.diff);
  });

  // 집계는 sync 대상 (제외 채널 아닌 것) 기준
  const syncable = rows.filter(r => !r.excluded);
  const totalDB = syncable.reduce((s, r) => s + r.db, 0);
  const totalDC = syncable.reduce((s, r) => s + r.dc, 0);
  const needUp = syncable.filter(r => r.needsSync && r.diff > 0).reduce((s, r) => s + r.diff, 0);
  const needDown = syncable.filter(r => r.needsSync && r.diff < 0).reduce((s, r) => s + (-r.diff), 0);
  const syncedCh = syncable.filter(r => !r.needsSync).length;  // minor 도 동기화됨으로 카운트
  const needCh = syncable.length - syncedCh;

  const allSelected = needCh > 0 && syncable.filter(r => r.needsSync).every(r => _syncSelectedChannels.has(r.ch));

  host.innerHTML = `
    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center;padding:10px 14px;background:var(--panel);border:1px solid var(--border-soft);border-radius:8px;margin-bottom:10px;font-size:12px">
      <div><span style="color:var(--text-dim)">DB:</span> <b>${totalDB.toLocaleString()}</b></div>
      <div><span style="color:var(--text-dim)">Discord:</span> <b>${totalDC.toLocaleString()}</b></div>
      ${needUp > 0 ? `<div style="color:var(--warn)">⬆ ${needUp.toLocaleString()}건 복원 예정</div>` : ''}
      ${needDown > 0 ? `<div style="color:var(--err)">⬇ ${needDown.toLocaleString()}건 삭제 예정</div>` : ''}
      ${(needUp === 0 && needDown === 0) ? '<div style="color:var(--ok)">✓ 완전 동기화 상태</div>' : ''}
      <div style="flex:1"></div>
      <div style="color:var(--text-dim)">${syncedCh}/${syncable.length} 동기화됨</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px">
        <input type="checkbox" id="scan-toggle-all" ${allSelected ? 'checked' : ''} onchange="scanToggleAll(this.checked)">
        <b>싱크 필요한 ${needCh}개 전체 선택</b>
      </label>
      <div style="flex:1"></div>
      <div style="color:var(--text-dim);font-size:11.5px">
        선택: <b id="scan-selected-count">${_syncSelectedChannels.size}</b>개
      </div>
      <button class="act-btn success" onclick="runSyncWithSelection()" ${_syncSelectedChannels.size === 0 ? 'disabled' : ''}>
        ▶ 선택한 ${_syncSelectedChannels.size}개 채널 싱크
      </button>
    </div>
    <div style="max-height:360px;overflow-y:auto;border:1px solid var(--border-soft);border-radius:8px">
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead style="background:var(--panel-2);position:sticky;top:0">
          <tr>
            <th style="text-align:left;padding:8px 10px;font-weight:600;width:34px"></th>
            <th style="text-align:left;padding:8px 10px;font-weight:600">채널</th>
            <th style="text-align:right;padding:8px 10px;font-weight:600;width:70px">DB</th>
            <th style="text-align:right;padding:8px 10px;font-weight:600;width:70px">Discord</th>
            <th style="text-align:left;padding:8px 14px;font-weight:600">상태</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => {
            const info = _chDiffInfo(r.db, r.dc);
            const checked = _syncSelectedChannels.has(r.ch);
            // 제외 채널은 무조건 비활성 + 딤처리. 동기화된 채널도 체크 비활성.
            // tolerance 안 인 minor drift 도 disabled — sync 필요 X 로 표시.
            // 그래도 사용자가 명시 sync 원하면 dim 행 풀고 수동 체크 가능 (체크박스만 enabled).
            const disabled = r.excluded || (!r.needsSync && !r.isMinor);
            let statusLabel;
            let color;
            if (r.excluded) {
              statusLabel = '— sync 제외 (로그 채널)';
              color = 'var(--text-dim)';
            } else if (r.needsSync) {
              statusLabel = info.label;
              color = r.diff > 0 ? 'var(--warn)' : 'var(--err)';
            } else if (r.isMinor) {
              statusLabel = `✓ 동기화됨 (작은 drift ${Math.abs(r.diff)}건 — split mismatch 등 비파괴)`;
              color = 'var(--text-dim)';
            } else {
              statusLabel = info.label;
              color = 'var(--text-dim)';
            }
            const rowStyle = r.excluded ? 'opacity:0.5' : '';
            return `
              <tr style="border-top:1px solid var(--border-soft);${rowStyle}">
                <td style="padding:6px 10px">
                  <input type="checkbox" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}
                    ${r.excluded ? `title="mgr-system-log 은 런타임 로그 채널이라 메시지 동기화 제외"` : ''}
                    onchange="scanToggleChannel('${esc(r.ch)}', this.checked)">
                </td>
                <td style="padding:6px 10px;font-family:'JetBrains Mono',monospace;font-size:11.5px">#${esc(r.ch)}</td>
                <td style="padding:6px 10px;text-align:right;color:var(--text-dim)">${r.db}</td>
                <td style="padding:6px 10px;text-align:right;color:var(--text-dim)">${r.dc}</td>
                <td style="padding:6px 14px;color:${color}">${statusLabel}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function scanToggleChannel(ch, checked) {
  if (checked) _syncSelectedChannels.add(ch);
  else _syncSelectedChannels.delete(ch);
  renderScanTable();
}

function scanToggleAll(checked) {
  if (!_lastScanResult) return;
  const dc = _lastScanResult.counts || {};
  const dbC = _lastScanResult.db_counts || {};
  const allChs = new Set([...Object.keys(dc), ...Object.keys(dbC)]);
  if (checked) {
    for (const ch of allChs) {
      if (MSG_SYNC_EXCLUDED.has(ch)) continue;
      if ((dbC[ch] || 0) !== (dc[ch] || 0)) _syncSelectedChannels.add(ch);
    }
  } else {
    _syncSelectedChannels.clear();
  }
  renderScanTable();
}

function runSyncWithSelection() {
  if (_syncSelectedChannels.size === 0) { toast('싱크할 채널을 선택해', 'warn'); return; }
  runSyncAction('sync', { channels: [..._syncSelectedChannels] });
}

async function runSyncAction(action, extraBody) {
  if (_syncInProgress) { toast('이미 sync 작업 중', 'warn'); return; }
  const endpoints = {
    scan: '/api/action/scan_discord',
    sync: '/api/action/run_sync',
    arrange: '/api/action/arrange_channels',
    restore: '/api/action/restore',
  };
  const labels = { scan: 'Scan Discord', sync: 'Full Sync', arrange: '채널 순서 정렬', restore: 'Restore Messages' };
  const cancellable = (action === 'scan' || action === 'arrange');
  openSyncModal(labels[action], cancellable);
  const appendOut = appendSyncLog;
  _syncAbortCtrl = new AbortController();

  const running = await isBotRunning();
  let restartAfter = false;

  if (running) {
    if (!confirm(`${labels[action]}를 실행하려면 서버 일시 중단이 필요. 중단 → 실행 → 재시작 자동으로 진행할까?`)) {
      appendOut('❌ 취소됨');
      finishSyncModal(false);
      return;
    }
    restartAfter = true;
    appendOut('⏸ 서버 중단 중...');
    const stopR = await postJson(q('/api/action/stop_server'), {});
    if (stopR.error) { appendOut(`❌ 중단 실패: ${stopR.message || stopR.error}`); toast('중단 실패', 'err'); finishSyncModal(false); return; }
    appendOut(`✓ 프로세스 ${stopR.count}개 종료`);
    const stopped = await waitFor(async () => !(await isBotRunning()), 1000, 30);
    if (!stopped) { appendOut('⚠ 서버가 여전히 running 감지 — 계속 진행'); }
    appendOut('● 서버 오프라인 확인');
  }

  appendOut(`▶ ${labels[action]} 실행 중...`);
  let r;
  try {
    const fetchOpts = cancellable ? { signal: _syncAbortCtrl.signal } : {};
    r = await postJson(q(endpoints[action]), extraBody || {}, fetchOpts);
  } catch (e) {
    if (e.name === 'AbortError') {
      appendOut('⏹ 사용자 취소로 중단됨');
      toast('취소됨', 'warn');
      finishSyncModal(false);
      return;
    }
    appendOut(`❌ 요청 오류: ${e.message}`);
    toast(e.message, 'err');
    finishSyncModal(false);
    return;
  }
  if (r.error) {
    appendOut(`❌ ${r.message || r.error}`);
    toast(r.message || r.error, 'err');
  } else {
    appendOut('✓ 완료');
    // Scan 결과는 global state 에 저장 → 테이블로 렌더
    if (action === 'scan' && r.result) {
      _lastScanResult = r.result;
      // 이전 선택 초기화 후 diff 있는 채널 자동 선택
      _syncSelectedChannels.clear();
      const dc = r.result.counts || {};
      const dbC = r.result.db_counts || {};
      for (const ch of new Set([...Object.keys(dc), ...Object.keys(dbC)])) {
        if (MSG_SYNC_EXCLUDED.has(ch)) continue;
        if ((dbC[ch] || 0) !== (dc[ch] || 0)) _syncSelectedChannels.add(ch);
      }
      const totalDiff = Object.keys(dc).length + Object.keys(dbC).length;
      appendOut(`  스캔 완료: ${r.result.channels_scanned}개 채널 · Discord 총 ${r.result.total}건`);
      appendOut(`  싱크 필요: ${_syncSelectedChannels.size}개 채널 (체크됨)`);
      renderScanTable();
    } else {
      if (r.logs && r.logs.length) appendOut(r.logs.join('\n'));
      if (r.result) appendOut(JSON.stringify(r.result, null, 2));
    }
    // Sync 완료 후엔 자동 재스캔 → 실제 clean 상태를 `_lastScanResult` 에 저장.
    // 이전엔 cache 만 무효화 (null) 해서 테이블은 비어있어도 실제 검증 안 한 상태였음.
    // → 가동 시 overlay 가 fresh scan 하면 재전송 실패 같은 drift 를 새로 찾아내 sync 탭과
    //   상태가 엇갈려 보이는 문제. 이제 sync 직후 한번 더 scan 해서 실제로 clean 인지 확인.
    if (action === 'sync') {
      _syncSelectedChannels.clear();
      appendOut('\n▶ 싱크 후 재검증 스캔...');
      try {
        const vr = await postJson(q('/api/action/scan_discord'), {});
        if (vr && vr.result) {
          _lastScanResult = vr.result;
          const dc = vr.result.counts || {};
          const dbC = vr.result.db_counts || {};
          let drift = 0;
          for (const ch of new Set([...Object.keys(dc), ...Object.keys(dbC)])) {
            if (MSG_SYNC_EXCLUDED.has(ch)) continue;
            if ((dbC[ch] || 0) !== (dc[ch] || 0)) drift++;
          }
          appendOut(drift === 0 ? '✓ 재검증: drift 없음' : `⚠ 재검증: ${drift}개 채널 여전히 drift`);
          renderScanTable();
        } else {
          _lastScanResult = null;
          renderScanTable();
        }
      } catch (_e) {
        _lastScanResult = null;
        renderScanTable();
      }
    }
    toast(`${labels[action]} 완료`, 'ok');
  }

  if (restartAfter) {
    appendOut('\n▶ 서버 재시작 중...');
    const startR = await postJson(q('/api/action/start_server'), {});
    if (startR.error) { appendOut(`⚠ 재시작 실패: ${startR.message || startR.error}`); toast('재시작 실패 — 수동 기동 필요', 'err', 5000); }
    else { appendOut('● 서버 재시작 요청됨 (10~20초 후 online)'); toast('서버 재시작 중', 'ok'); }
  }
  finishSyncModal(!r.error);
  tick();
}

async function doChannelClear(channel) {
  if (!confirm(`#${channel}의 DB 메시지 전체 삭제. Discord 채널은 유지. 진행?`)) return;
  const r = await postJson(q('/api/action/channel_clear'), {channel});
  if (r.error) return toast(r.message || r.error, 'err');
  toast(`#${channel} 메시지 ${r.deleted?.deleted_count || '?'}개 삭제됨`, 'ok');
  closeModal();
  tick();
}

async function doChannelDelete(channel) {
  if (!confirm(`채널 #${channel} 완전 삭제. ${channel.startsWith('mgr-') ? 'mgr 채널은 보호돼야 함!' : '복구 어려움.'} 진행?`)) return;
  const r = await postJson(q('/api/action/channel_delete'), {channel});
  if (r.error) return toast(r.message || r.error, 'err');
  toast(`#${channel} 삭제됨. ${r.note || ''}`, 'ok');
  closeModal();
  tick();
}

async function loadTrash() {
  const r = await postJson(q('/api/action/trash_list'), {});
  const countEl = document.getElementById('trash-count');
  const listEl = document.getElementById('trash-list');
  if (!r.ok) {
    if (countEl) countEl.textContent = 'error';
    return;
  }
  const items = r.items || [];
  if (countEl) countEl.textContent = `${items.length}건`;
  if (!listEl) return;
  listEl.innerHTML = items.length ? items.slice(0, 30).map(t =>
    `<div class="trash-item">
      <span class="ch">#${esc(t.channel || '')}</span>
      <span class="who">${esc(t.speaker || '')}</span>
      <span class="msg">${esc((t.message || '').slice(0, 80))}</span>
      <button class="act-btn small" onclick="restoreTrash(${t.id})">복구</button>
    </div>`
  ).join('') : '<div class="empty">trash empty</div>';
}

async function restoreTrash(tid) {
  const r = await postJson(q('/api/action/trash_restore'), {trash_id: tid});
  if (r.error) return toast(r.message || r.error, 'err');
  toast('복구됨', 'ok');
  loadTrash();
  tick();
}

async function emptyTrash() {
  if (!confirm('Trash 전체 비우기. 되돌릴 수 없음. 진행?')) return;
  const r = await postJson(q('/api/action/trash_empty'), {});
  if (r.error) return toast(r.message || r.error, 'err');
  toast('Trash 비워짐', 'ok');
  loadTrash();
}

async function runServerControl(action) {
  const labels = { start: '시작', stop: '중단', restart: '재시작' };
  const endpoints = { start: 'start_server', stop: 'stop_server', restart: 'restart_server' };
  // Health 탭의 server-log → Sync 탭의 sync-output → 아무것도 없으면 toast 만. DOM 가변성 방어.
  const out = document.getElementById('health-server-log') || document.getElementById('sync-output');
  const appendOut = (s) => { if (out) { out.textContent += s + '\n'; out.scrollTop = out.scrollHeight; } };
  if (action === 'stop' && !confirm('커뮤니티 서버 중단?')) return;
  if (action === 'restart' && !confirm('서버 재시작? (10~20초 소요)')) return;

  if (out) out.textContent = `▶ 서버 ${labels[action]} 중...\n`;
  toast(`서버 ${labels[action]} 요청 중...`, 'ok', 2000);
  const r = await postJson(q(`/api/action/${endpoints[action]}`), {});
  if (r.error) {
    appendOut(`❌ ${r.message || r.error}`);
    toast(`서버 ${labels[action]} 실패: ${r.message || r.error}`, 'err', 5000);
    return;
  }
  appendOut(`✓ 서버 ${labels[action]} 요청 완료`);
  if (r.count !== undefined) appendOut(`  종료된 프로세스: ${r.count}개`);
  if (r.mode) appendOut(`  mode: ${r.mode}`);
  if (r.message) appendOut(`  ${r.message}`);
  toast(`서버 ${labels[action]} ${action === 'stop' ? '완료' : '중'}`, 'ok', 3000);
  // Stop 은 즉시 상태 반영 (stop marker 덕분), Start/Restart 는 봇 로그 뜨기까지 몇 초 → 여러 번 refresh
  setTimeout(() => { tick(); loadCommunities(); }, 1000);
  setTimeout(() => { tick(); loadCommunities(); }, 5000);
  if (action !== 'stop') setTimeout(() => { tick(); loadCommunities(); }, 15000);
}

// ==== Main tick ====
// ==== Supervisors (agent card 포맷으로 재사용) ====
// name 기반 친화 표시명 매핑
const SUP_DISPLAY_NAME = {
  'tutorial': 'Tutorial',
  'channel-conv': 'Channel Conversation',
};
function supDisplayName(name) {
  return SUP_DISPLAY_NAME[name] || name;
}
function supervisorAsAgent(s) {
  const statusEmoji = s.intervening ? '🔥' : (s.active ? '💭' : '💤');
  const emotion = s.intervening ? '개입 중' : (s.active ? '감시 중' : '대기');
  return {
    id: `sup:${s.name}`,
    type: 'supervisor',
    name: supDisplayName(s.name),
    status: s.active ? 'active' : 'inactive',
    emotion,
    emoji: s.icon || statusEmoji,
    intensity: s.intervening ? 10 : (s.active ? 5 : 0),
    mbti: '',
    age: 0,
    last_active: s.last_action || '',
    thinking: s.intervening,
    speaking: false,
    thinking_seconds: s.seconds_since_action || 0,
    speaking_seconds: 0,
    // supervisor는 Haiku judge + Sonnet inject 혼용
    model: 'claude-haiku-4-5 · claude-sonnet-4-6',
    provider: 'claude',
    model_override: false,
    _sup: s,  // 원본 supervisor 데이터
  };
}

function renderSupervisorsTab(supervisors) {
  if (!supervisors || !supervisors.length) {
    return '<div class="empty">등록된 감시자 없음</div>';
  }
  const active = supervisors.filter(s => s.active);
  const inactive = supervisors.filter(s => !s.active);

  const renderGroup = (title, arr, hint) => {
    if (!arr.length) return '';
    // renderAgent 재사용 — 같은 양식으로 렌더. agent-grid로 감싸서 hover/layout 동일.
    const cards = arr.map(s => renderAgent(supervisorAsAgent(s))).join('');
    return `<div class="detail-section"${title === 'Active' ? ' style="margin-top:0"' : ''}>
      <h4>${esc(title)} · ${arr.length}</h4>
      ${hint ? `<div style="color:var(--text-dim);font-size:11.5px;margin-bottom:10px">${esc(hint)}</div>` : ''}
      <div class="agent-grid">${cards}</div>
    </div>`;
  };

  return [
    renderGroup('Active', active, '현재 조건 충족 — 백그라운드 감시 중'),
    renderGroup('Idle', inactive, '현재 조건 미충족 — 트리거 대기'),
  ].join('');
}

// 그래프 구조 서명 — 다르면 재렌더, 같으면 live 상태만 업데이트
let lastGraphSig = null;
// 리스트 재렌더 가드 — 의미있는 변화 없으면 innerHTML 안 건드림 (아바타 img 재생성 깜빡임 방지).
// relative-time(ago/elapsed) 은 시그니처에서 제외 → idle 정지 상태에선 재렌더 0.
let lastAgentsSig = null, lastMsgSig = null, lastChannelsSig = null;
function agentsSignature(agents) {
  return agents.map(a => [a.id, a.name, a.type, a.emotion, a.intensity_band ?? a.intensity,
    a.thinking ? 1 : 0, a.speaking ? 1 : 0, a.status, a.model].join('~')).join('|');
}
function messagesSignature(msgs) {
  if (!msgs || !msgs.length) return '0';
  const last = msgs[msgs.length - 1];
  return msgs.length + '~' + (last.id ?? (last.speaker + '|' + last.ts + '|' + (last.message || '').length));
}
function channelsSignature(chs) {
  return (chs || []).map(c => c.name + '~' + c.msg_count + '~' + c.status + '~' + (c.participant_count ?? '')).join('|');
}
function graphSignature(snap) {
  const agents = snap.agents.map(a => a.id).sort().join(',');
  const chans = (snap.channels || [])
    .filter(c => c.msg_count > 0 || c.status === 'running')
    .map(c => `${c.name}:${c.participant_count}:${c.status}`)
    .sort().join('|');
  const sups = SHOW_SUP
    ? (snap.supervisors || []).map(s => `${s.name}:${s.active ? 1 : 0}`).sort().join(',')
    : '';
  return `${agents}||${chans}||${sups}||${SHOW_SUP ? 1 : 0}||${document.body.classList.contains('graph-fullscreen') ? 'fs' : 'n'}`;
}

// ==== Connection Graph (Cytoscape.js) ====
// 자체 제작 SVG 그래프(휴리스틱 충돌회피, 라벨 push 등) 폐기 → cytoscape.js
//   - 데이터 빌드: snap → cy elements (nodes / edges) 만 책임
//   - 레이아웃 / 충돌회피 / 라벨배치 / 다중엣지 spread = 라이브러리에 위임
//   - signature 변할 때 destroy + recreate, live 상태만 변하면 cy.batch()로 클래스 토글
let cyInstance = null;

let cyLiveAnimTimer = null;
function destroyCyGraph() {
  if (cyLiveAnimTimer) { clearInterval(cyLiveAnimTimer); cyLiveAnimTimer = null; }
  if (cyInstance) {
    try { cyInstance.destroy(); } catch (e) {}
    cyInstance = null;
  }
}

// 추론/발화 중 노드: border-width + 색상 펄스 (skin-of-the-teeth halo via underlay-padding)
let cyNodePulseTimer = null;
let cyNodePulsePrev = [];
function _resetNodeInlineStyle(n) {
  try { n.removeStyle('border-width underlay-color underlay-padding underlay-opacity underlay-shape'); }
  catch (e) {}
}
function startNodePulseAnimation() {
  if (!cyInstance) return;
  if (cyNodePulseTimer) { clearInterval(cyNodePulseTimer); cyNodePulseTimer = null; }
  // 이전 라운드에서 펄스 적용한 노드들의 inline 스타일 제거 (class 빠진 노드 깨끗이)
  for (const n of cyNodePulsePrev) {
    if (!n.hasClass('thinking') && !n.hasClass('speaking')) _resetNodeInlineStyle(n);
  }
  // 오프라인 (stale flag)이면 펄스 안 함 — agent-card와 동일 정책
  if (document.body.classList.contains('offline')) {
    cyInstance.nodes('.thinking, .speaking').forEach(_resetNodeInlineStyle);
    cyNodePulsePrev = [];
    return;
  }
  const liveNodes = cyInstance.nodes('.thinking, .speaking');
  cyNodePulsePrev = liveNodes.toArray();
  if (liveNodes.length === 0) return;
  let pulse = 0;
  cyNodePulseTimer = setInterval(() => {
    pulse = (pulse + 0.06) % (Math.PI * 2);
    const sin = Math.sin(pulse);
    const ease = (sin + 1) * 0.5;            // 0 ~ 1
    const borderWidth = 4.5 + ease * 1.0;    // 4.5 ~ 5.5
    const underlayPad = 2 + ease * 6;        // 2 ~ 8
    const underlayOp = 0.10 + ease * 0.18;   // 0.10 ~ 0.28
    cyInstance.batch(() => {
      liveNodes.forEach(n => {
        const isSpeak = n.hasClass('speaking');
        const color = isSpeak ? n.cy().scratch('_speakingColor') : n.cy().scratch('_thinkingColor');
        n.style({
          'border-width': borderWidth,
          'underlay-color': color,
          'underlay-padding': underlayPad,
          'underlay-opacity': underlayOp,
          'underlay-shape': 'ellipse',
        });
      });
    });
  }, 60);
}

// 라이브(활성) 엣지: 굵기 + 글로우 padding 펄스 — solid line 위로 pulsing halo 효과
function startLiveEdgeAnimation() {
  if (!cyInstance) return;
  if (cyLiveAnimTimer) { clearInterval(cyLiveAnimTimer); cyLiveAnimTimer = null; }
  const liveEdges = cyInstance.edges('.live');
  if (liveEdges.length === 0) return;
  // 오프라인이면 정적 라인만
  if (document.body.classList.contains('offline')) {
    cyInstance.batch(() => {
      liveEdges.forEach(e => e.style({ 'width': 2, 'opacity': 0.5, 'overlay-opacity': 0 }));
    });
    return;
  }
  // 점선 플로우 — dash-offset 을 한 방향으로 이동 ("대화가 흐르는" 느낌)
  // + width 미세 호흡. 과한 글로우(overlay) 는 제거 — paper 톤 유지.
  let pulse = 0;
  let dash = 0;
  cyLiveAnimTimer = setInterval(() => {
    pulse = (pulse + 0.1) % (Math.PI * 2);
    dash -= 1.3;
    if (dash < -10000) dash = 0;
    const width = 2.4 + Math.sin(pulse) * 0.4;
    cyInstance.batch(() => {
      liveEdges.forEach(e => {
        e.style({
          'width': width,
          'line-dash-offset': dash,
          'overlay-opacity': 0,
        });
      });
    });
  }, 50);
}

// 구조 동일 → 노드 live 상태(thinking/speaking, sup active/intervening) cy 클래스 토글
function updateGraphLiveState(snap) {
  if (!cyInstance) return;
  const agentMap = {};
  for (const a of snap.agents) agentMap[a.id] = a;
  // 채널별 활성 상태 재계산 (recent OR party thinking/speaking)
  const liveChannels = new Set();
  for (const c of (snap.channels || [])) {
    const recent = c.last_ago && (
      c.last_ago === '방금' ||
      c.last_ago.includes('초') ||
      (c.last_ago.includes('분') && parseInt(c.last_ago) < 2)
    );
    // 채널-aware 매칭 — agent.thinking 만 보면 그 에이전트가 참여한 모든 채널이 live 로 잘못 표시.
    // thinking_channel / speaking_channel 이 현재 채널과 일치할 때만 party live.
    const party = (c.participants || []).some(pid => {
      const ag = agentMap[pid];
      if (!ag) return false;
      if (ag.thinking && ag.thinking_channel === c.name) return true;
      if (ag.speaking && ag.speaking_channel === c.name) return true;
      // 옛 데이터 (thinking_channel 없는 경우) — 전체 thinking 으로 폴백 안 함. live 안 켜는 게 안전.
      return false;
    });
    if (recent || party) liveChannels.add(c.name);
  }
  let liveCountChanged = false;
  cyInstance.batch(() => {
    for (const a of snap.agents) {
      const n = cyInstance.getElementById(a.id);
      if (n.empty()) continue;
      n.toggleClass('thinking', !!a.thinking);
      n.toggleClass('speaking', !!a.speaking);
    }
    cyInstance.edges().forEach(e => {
      const ch = e.data('channel');
      const wasLive = e.hasClass('live');
      const nowLive = liveChannels.has(ch);
      if (wasLive !== nowLive) {
        e.toggleClass('live', nowLive);
        liveCountChanged = true;
        // live → idle 전환 시 애니메이션 inline style 초기화 — 안 하면 마지막 프레임의
        // width/overlay 가 잔상으로 남아 회색 점선 class style 이 먹히지 않음.
        if (!nowLive) {
          e.removeStyle('width');
          e.removeStyle('overlay-color');
          e.removeStyle('overlay-opacity');
          e.removeStyle('overlay-padding');
          e.removeStyle('opacity');
        }
      }
    });
    if (SHOW_SUP) {
      for (const s of (snap.supervisors || [])) {
        const n = cyInstance.getElementById('sup:' + s.name);
        if (n.empty()) continue;
        n.toggleClass('active', !!s.active);
        n.toggleClass('intervening', !!s.intervening);
      }
    }
  });
  if (liveCountChanged) {
    startLiveEdgeAnimation();
  }
  startNodePulseAnimation();
}

// snap → { nodes, edges } cytoscape elements
function buildGraphElements(snap) {
  const ownerName = snap.meta?.user_name || 'Owner';
  const idToAgent = {};
  for (const a of snap.agents) idToAgent[a.id] = a;

  // 활성 채널만 (msg_count > 0 또는 running)
  const channels = (snap.channels || []).filter(c => {
    if (c.participant_count < 1) return false;
    return c.msg_count > 0 || c.status === 'running';
  });

  // raw edges — 채널 단위 + 참여자 모든 쌍 조합 (그룹 채널이면 N choose 2 개 엣지)
  const rawEdges = [];
  const involvedAgentIds = new Set();
  let ownerInvolved = false;
  for (const c of channels) {
    const parts = [];
    const includeOwner = (c.kind === 'dm' || c.kind === 'group' || c.kind === 'mgr');
    if (includeOwner) { parts.push('__owner__'); ownerInvolved = true; }
    for (const pid of (c.participants || [])) {
      if (idToAgent[pid]) {
        parts.push(pid);
        involvedAgentIds.add(pid);
      }
    }
    if (parts.length < 2) continue;
    // 활성 판정: 최근 발화 OR 참여자(에이전트 또는 owner) 중 한 명이라도 활동 중
    const recentLive = c.last_ago && (
      c.last_ago === '방금' ||
      c.last_ago.includes('초') ||
      (c.last_ago.includes('분') && parseInt(c.last_ago) < 2)
    );
    const partyLive = (c.participants || []).some(pid => {
      const ag = idToAgent[pid];
      return ag && (ag.thinking || ag.speaking);
    });
    // owner가 채널의 활동 주체일 수도 있음 — last_speaker 가 owner 면 즉시 활성
    const ownerActive = includeOwner && c.last_speaker && (
      c.last_speaker.startsWith('user') ||
      c.last_speaker === 'test-user' ||
      c.last_speaker === 'owner'
    ) && recentLive;
    const live = recentLive || partyLive || ownerActive;
    for (let i = 0; i < parts.length; i++) {
      for (let j = i + 1; j < parts.length; j++) {
        rawEdges.push({
          source: parts[i],
          target: parts[j],
          channel: c.name,
          kind: c.kind,
          live,
          msg_count: c.msg_count,
        });
      }
    }
  }

  // 엣지 없어도 mgr/creator 는 항상 표시. dev (한세나) 는 supervisor view 토글 ON 일 때만.
  for (const a of snap.agents) {
    if (a.type === 'mgr' || a.type === 'creator') involvedAgentIds.add(a.id);
    else if (a.type === 'dev' && SHOW_SUP) involvedAgentIds.add(a.id);
  }

  // 노드 정렬: mgr → creator → dev → persona (concentric 배치 순서 결정)
  const typeRank = { mgr: 0, creator: 1, dev: 2, persona: 3 };
  const sortedAgentIds = Array.from(involvedAgentIds).sort((a, b) => {
    const ra = typeRank[idToAgent[a]?.type] ?? 9;
    const rb = typeRank[idToAgent[b]?.type] ?? 9;
    return ra - rb;
  });

  const nodes = [];
  if (ownerInvolved) {
    nodes.push({
      data: { id: '__owner__', label: ownerName, kind: 'owner' },
      classes: 'owner',
    });
  }
  for (const aid of sortedAgentIds) {
    const a = idToAgent[aid];
    if (!a) continue;
    const liveCls = a.thinking ? 'thinking' : a.speaking ? 'speaking' : '';
    // status 'inactive' 면 dim 처리 — dev agent (한세나) 가 큐 비어있을 때.
    // thinking/speaking 중이면 inactive 무시 (live 가 우선).
    const inactiveCls = (a.status === 'inactive' && !liveCls) ? 'inactive' : '';
    const avatar = `/api/avatar?id=${encodeURIComponent(a.id)}${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
    nodes.push({
      data: { id: a.id, label: a.name, kind: 'agent', agentType: a.type, avatar },
      classes: ('agent ' + a.type + ' ' + liveCls + ' ' + inactiveCls).trim(),
    });
  }

  // Supervisor 노드 + 엣지
  const supEdges = [];
  if (SHOW_SUP && snap.supervisors) {
    const visibleSups = snap.supervisors.filter(s => {
      const tn = (s.target_agents || []).filter(aid => involvedAgentIds.has(aid));
      return tn.length > 0 || s.active || s.intervening;
    });
    for (const s of visibleSups) {
      const supId = 'sup:' + s.name;
      const cls = ['sup'];
      if (s.active) cls.push('active');
      if (s.intervening) cls.push('intervening');
      // 아이콘 이모지 → SVG text. viewBox 200x200 + 작은 font-size → diamond shape 안에 안전하게 fit
      const iconChar = s.icon || '◆';
      const iconSvg = 'data:image/svg+xml;utf8,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><text x="100" y="125" font-size="80" text-anchor="middle" font-family="-apple-system,Segoe UI Emoji,Apple Color Emoji,Noto Color Emoji,sans-serif">' + iconChar + '</text></svg>'
      );
      nodes.push({
        data: { id: supId, label: supDisplayName(s.name), kind: 'sup', icon: iconChar, iconSvg },
        classes: cls.join(' '),
      });
      const activeTargets = new Set(s.active_targets || []);
      for (const aid of (s.target_agents || [])) {
        if (!involvedAgentIds.has(aid)) continue;
        let ec = 'sup-edge ';
        // 우선순위: 최근 30분 내 실제 이벤트 → 'recent' (가장 강조)
        //          intervening (현 진행) → 'intervening'
        //          active (활성) → 'active'
        //          그 외 → 'idle'
        if (activeTargets.has(aid)) ec += 'recent';
        else if (s.intervening) ec += 'intervening';
        else if (s.active) ec += 'active';
        else ec += 'idle';
        supEdges.push({
          data: { id: 'supedge:' + s.name + ':' + aid, source: supId, target: aid, kind: 'sup', label: '' },
          classes: ec,
        });
      }
    }
  }

  // cy edges (unique IDs, 라벨 = 채널명, 너무 길면 잘라냄)
  //   owner spoke 면 source=__owner__ target=agent 순서 보장됨 (위 parts 빌드 순서)
  //   → target-label 로 렌더하면 라벨이 agent 쪽 끝에 붙어 owner 중심에서 분산됨
  const truncLabel = (s) => (s.length > 16 ? s.slice(0, 14) + '…' : s);
  const edges = rawEdges.map((e, i) => ({
    data: {
      id: 'e' + i,
      source: e.source,
      target: e.target,
      label: truncLabel(e.channel),
      channel: e.channel,
      kind: e.kind,
      msgCount: e.msg_count || 0,
      cpd: 0,
      cpw: 0.5,
    },
    classes: 'ch-' + e.kind + (e.live ? ' live' : ''),
  }));

  // 가장 강한 관계 (msg 수 최대) 엣지에 상시 배지 — 두께+숫자 이중 인코딩
  let topTie = null;
  for (const e of edges) {
    if (!topTie || e.data.msgCount > topTie.data.msgCount) topTie = e;
  }
  if (topTie && topTie.data.msgCount > 0) {
    topTie.classes += ' top-tie';
    topTie.data.badge = topTie.data.msgCount >= 1000
      ? (topTie.data.msgCount / 1000).toFixed(1) + 'k'
      : String(topTie.data.msgCount);
  }

  // 같은 source-target 페어가 여러 개면 perpendicular 방향으로 spread
  //   → unbundled-bezier 의 control-point-distances 에 페어별 인덱스 기반 offset 부여
  //   → 단일 엣지면 cpd=0 (직선)
  const pairBuckets = {};
  for (const e of edges) {
    const k = [e.data.source, e.data.target].sort().join('||');
    (pairBuckets[k] = pairBuckets[k] || []).push(e);
  }
  const PAIR_SPREAD = 38;  // 인접 엣지 간 px 거리
  for (const k in pairBuckets) {
    const grp = pairBuckets[k];
    const n = grp.length;
    if (n <= 1) continue;
    grp.forEach((e, i) => {
      e.data.cpd = (i - (n - 1) / 2) * PAIR_SPREAD;
    });
  }

  return { nodes, edges: edges.concat(supEdges) };
}

function pickGraphLayout(nodeCount, fullscreen, hasSup) {
  // concentric — owner 중앙, agents 외곽 ring, supervisors 더 외곽.
  // 슈퍼바이저 노드가 섞여 있는데 전체 노드가 적으면 (≤5) supervisor 가 외곽 ring 에
  // 고립되어 못생김 → 그때만 cose 폴백. 그 외엔 concentric 로 통일해서 mgr 이 맨 위
  // (startAngle -π/2), creator 가 그 다음 시계방향 (오른쪽) 에 오도록.
  // buildGraphElements 에서 typeRank 로 mgr → creator → persona 순 정렬됨.
  if (hasSup && nodeCount <= 5) {
    return {
      name: 'cose',
      fit: true,
      padding: fullscreen ? 140 : 40,
      animate: false,
      nodeRepulsion: () => 6500,
      idealEdgeLength: () => nodeCount <= 3 ? 120 : 90,
      edgeElasticity: () => 100,
      gravity: 0.2,
      numIter: 800,
    };
  }
  // 레이아웃 자체는 데스크 비율 유지 (사용자: "에이전트 간 거리는 이전이 적절").
  // 모바일은 fit() 의 padding 만 작게 → zoom-out 으로 viewport 안에 수렴.
  const minSpace = nodeCount <= 8 ? 75 : 50;
  const spacingF = 1.25;
  const isMobile = (typeof window !== 'undefined') &&
                   window.matchMedia && window.matchMedia('(max-width: 720px)').matches;
  return {
    name: 'concentric',
    concentric: function(node) {
      const k = node.data('kind');
      if (k === 'owner') return 3;
      if (k === 'agent') return 2;
      return 1;
    },
    levelWidth: function() { return 1; },
    minNodeSpacing: fullscreen ? minSpace * 1.4 : minSpace,
    spacingFactor: fullscreen ? spacingF * 1.25 : spacingF,
    avoidOverlap: true,
    fit: true,
    // 모바일은 padding 만 줄여서 같은 layout 을 더 zoom-out 으로 수렴 (비율 유지).
    padding: fullscreen ? 140 : (isMobile ? 6 : 25),
    startAngle: -Math.PI / 2,
    animate: false,
  };
}

function renderConnectionGraph(snap) {
  // 활성 채널 + mgr/creator 존재 여부만 빠르게 체크 → 빈 상태면 placeholder
  const fullscreen = document.body.classList.contains('graph-fullscreen');
  const channels = (snap.channels || []).filter(c =>
    c.participant_count >= 1 && (c.msg_count > 0 || c.status === 'running')
  );
  const hasMgrCreator = snap.agents.some(a => a.type === 'mgr' || a.type === 'creator');
  const hasContent = channels.length > 0 || hasMgrCreator;

  const headHtml = `<div class="graph-head">
      <h3>Connection Graph</h3>
      <span class="note" id="graph-note"></span>
    </div>`;

  if (!hasContent) {
    return headHtml + `<div class="graph-empty">활성 채널 없음 — 에이전트들이 조용히 대기 중</div>`;
  }

  // 캔버스 오버레이 — 칩 레전드(좌하단, 노드 타입 기준) + 플로팅 컨트롤(우하단)
  const chips = `<div class="graph-chips">
    <span class="gchip"><span class="gdot" style="background:var(--user)"></span>오너</span>
    <span class="gchip"><span class="gdot" style="background:var(--mgr)"></span>매니저</span>
    <span class="gchip"><span class="gdot" style="background:var(--creator)"></span>크리에이터</span>
    <span class="gchip"><span class="gdot" style="background:var(--persona)"></span>페르소나</span>
    ${SHOW_SUP ? `<span class="gchip"><span class="gdot" style="background:var(--warn)"></span>감시자</span>` : ''}
    <span class="gchip"><span class="gline" style="background:var(--speaking)"></span>대화 중</span>
  </div>`;
  const ctl = `<div class="graph-ctl">
    <button title="화면 맞춤" onclick="cyFitGraph()"><i class="ti ti-focus-2" aria-hidden="true"></i></button>
    <button title="${fullscreen ? '닫기' : '전체보기'}" onclick="toggleGraphFullscreen()"><i class="ti ${fullscreen ? 'ti-x' : 'ti-maximize'}" aria-hidden="true"></i></button>
  </div>`;

  return headHtml +
    `<div class="graph-stage"><div id="cy-graph" style="width:100%;height:100%"></div>${chips}${ctl}</div>`;
}

// 그래프 화면 맞춤 (플로팅 컨트롤)
function cyFitGraph() {
  if (!cyInstance) return;
  const isMobile = window.matchMedia('(max-width: 720px)').matches;
  cyInstance.fit(undefined, isMobile ? 6 : 25);
}

// renderConnectionGraph 후 호출 — innerHTML 으로 들어간 #cy-graph 에 cytoscape 인스턴스 마운트
function mountCytoscapeGraph(snap) {
  destroyCyGraph();
  const container = document.getElementById('cy-graph');
  if (!container || typeof cytoscape === 'undefined') return;

  const { nodes, edges } = buildGraphElements(snap);
  if (nodes.length === 0) return;

  const fullscreen = document.body.classList.contains('graph-fullscreen');

  // CSS variable → 실제 색상값 (cytoscape style 은 var() 못 읽음)
  const cs = getComputedStyle(document.body);
  const tok = (n) => (cs.getPropertyValue(n) || '').trim();
  const C = {
    text: tok('--text') || '#222',
    textDim: tok('--text-dim') || '#888',
    panel: tok('--panel') || '#fff',
    border: tok('--border') || '#ddd',
    accent: tok('--accent') || '#4b8',
    ok: tok('--ok') || '#5c5',
    warn: tok('--warn') || '#c93',
    err: tok('--err') || '#c33',
    mgr: tok('--mgr') || '#a6f',
    creator: tok('--creator') || '#fa3',
    persona: tok('--persona') || '#48f',
    dev: tok('--dev') || '#0891b2',
    user: tok('--user') || '#fb6',
    cmd: tok('--cmd') || '#d6f',
    thinking: tok('--thinking') || '#fc6',
    speaking: tok('--speaking') || '#6cf',
  };

  // 노드 크기 — 데스크/모바일 동일 (zoom-out 으로 모바일 fit). 라벨만 모바일에서 살짝 작게.
  const isMobileGraph = window.matchMedia && window.matchMedia('(max-width: 720px)').matches;
  const nodeSize = fullscreen ? 70 : 64;
  const ownerSize = fullscreen ? 66 : 60;
  const supSize = fullscreen ? 54 : 48;
  const fontSize = fullscreen ? 12 : (isMobileGraph ? 10 : 11.5);

  cyInstance = cytoscape({
    container,
    elements: { nodes, edges },
    minZoom: 0.5,
    maxZoom: 2.5,
    boxSelectionEnabled: false,
    autounselectify: true,
    // overview 모드 (default): 그래프 내부 휠/드래그 비활성
    //   → 페이지 전체 스크롤이 그래프 위에서도 자연스럽게 동작
    // fullscreen 모드: 줌/팬 가능
    userZoomingEnabled: fullscreen,
    userPanningEnabled: fullscreen,
    style: [
      // ===== Agent nodes (avatar 원) =====
      {
        selector: 'node.agent',
        style: {
          'shape': 'ellipse',
          'width': nodeSize,
          'height': nodeSize,
          'background-image': 'data(avatar)',
          'background-fit': 'cover cover',
          'background-color': C.panel,
          'border-width': 3,
          'border-color': C.border,
          'label': 'data(label)',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'color': C.text,
          'font-size': fontSize,
          'font-weight': 600,
          'text-background-color': C.panel,
          'text-background-opacity': 0.85,
          'text-background-padding': 3,
          'text-background-shape': 'roundrectangle',
          'text-border-color': C.border,
          'text-border-width': 0,
        },
      },
      { selector: 'node.agent.mgr', style: { 'border-color': C.mgr } },
      { selector: 'node.agent.creator', style: { 'border-color': C.creator } },
      { selector: 'node.agent.persona', style: { 'border-color': C.persona } },
      { selector: 'node.agent.dev', style: { 'border-color': C.dev } },
      {
        // Inactive agent (dev 가 큐 비어있을 때) — 회색 테두리 + 노드/라벨 흐리게.
        // thinking/speaking selector 보다 먼저 와야 — live 가 inactive 덮어쓰게.
        selector: 'node.agent.inactive',
        style: {
          'border-color': C.textDim,
          'border-style': 'dashed',
          'opacity': 0.55,
          'color': C.textDim,
        },
      },
      {
        selector: 'node.agent.thinking',
        style: { 'border-color': C.accent, 'border-width': 4, 'opacity': 1 },
      },
      {
        selector: 'node.agent.speaking',
        style: { 'border-color': C.speaking, 'border-width': 4, 'opacity': 1 },
      },
      // ===== Owner node — Material person SVG, viewBox 큼 + figure 가운데에 작게 =====
      //   shape:ellipse + bg-clip 으로 잘리는 문제 방지를 위해 figure 를 inscribed circle 안에 배치
      //   viewBox 200x200, figure 는 가운데 ~80x100 영역 (충분한 padding)
      {
        selector: 'node.owner',
        style: {
          'shape': 'ellipse',
          'width': ownerSize,
          'height': ownerSize,
          'background-color': '#fff5e6',
          'background-image': 'data:image/svg+xml;utf8,' + encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">' +
              '<circle cx="100" cy="80" r="26" fill="' + C.user + '"/>' +
              '<path d="M50 160 Q 50 116 100 116 Q 150 116 150 160 Z" fill="' + C.user + '"/>' +
            '</svg>'
          ),
          'background-fit': 'contain',
          'background-image-opacity': 1,
          'background-image-containment': 'inside',
          'border-width': 3,
          'border-color': C.user,
          'label': (snap.meta?.user_name || 'Owner'),
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'color': C.text,
          'font-size': fontSize,
          'font-weight': 700,
          'text-background-color': C.panel,
          'text-background-opacity': 0.85,
          'text-background-padding': 3,
          'text-background-shape': 'roundrectangle',
        },
      },
      // ===== Supervisor nodes (다이아몬드, 상태에 따른 styling) =====
      {
        selector: 'node.sup',
        style: {
          'shape': 'diamond',
          'width': supSize,
          'height': supSize,
          'background-color': C.panel,
          'background-image': 'data(iconSvg)',
          'background-fit': 'contain',
          'background-image-opacity': 0.55,  // 기본 idle — 흐릿
          'background-image-containment': 'inside',
          'border-width': 2,
          'border-style': 'dashed',
          'border-color': C.textDim,        // idle: 회색
          'opacity': 0.55,                   // 전체 dim
          'label': 'data(label)',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'color': C.textFaint,
          'font-size': 10,
          'font-weight': 600,
          'text-background-color': C.panel,
          'text-background-opacity': 0.85,
          'text-background-padding': 2,
          'text-background-shape': 'roundrectangle',
        },
      },
      // active — 감시 대상 있고 일 처리 중. solid + warn 색
      { selector: 'node.sup.active', style: {
          'border-style': 'solid',
          'border-color': C.warn,
          'opacity': 1,
          'background-image-opacity': 1,
          'color': C.text,
      }},
      {
        selector: 'node.sup.intervening',
        style: {
          'border-style': 'solid',
          'border-color': C.warn,
          'border-width': 4,
        },
      },
      // ===== Edges =====
      //   기본 (대기): dashed + 흐릿 → 범례의 "┄┄ 대기" 와 매칭
      //   live (활성): solid + 굵게 + 펄스 글로우 → "━━ 활성"
      {
        selector: 'edge',
        style: {
          'curve-style': 'unbundled-bezier',
          'control-point-distances': 'data(cpd)',
          'control-point-weights': 'data(cpw)',
          'width': 1.4,
          'line-color': C.textDim,
          'line-style': 'dashed',
          'line-dash-pattern': [4, 6],
          'target-arrow-shape': 'none',
          'opacity': 0.35,
          // 기본 라벨 숨김 — hover 시에만 보임 (라벨 떡짐 회피)
          //   midpoint label (target-label 대신 label) → 엣지 가운데에 깔끔히 배치
          'label': 'data(label)',
          'text-opacity': 0,
          'font-size': 11,
          'color': C.text,
          'text-background-color': C.panel,
          'text-background-opacity': 0.95,
          'text-background-padding': 2,
          'text-background-shape': 'roundrectangle',
          'text-border-color': C.border,
          'text-border-width': 1,
          'text-border-opacity': 0.6,
          'text-events': 'yes',
        },
      },
      // 채널 종류별 색상은 hover label 정도로만 활용. 기본 라인은 중성톤으로 통일해
      // 노드 컬러와 충돌하지 않게 (사용자 피드백: "엣지가 너무 튀어서 미감 망침")
      {
        // live — 대화 중인 관계. speaking 시안색 점선이 흐름 (dash-offset 애니메이션)
        selector: 'edge.live',
        style: {
          'line-style': 'dashed',
          'line-dash-pattern': [7, 6],
          'opacity': 0.9,
          'width': 2.4,
          'line-color': C.speaking,
        },
      },
      {
        // 최강 관계 배지 — accent 필 안에 메시지 수 상시 표시
        selector: 'edge.top-tie',
        style: {
          'label': 'data(badge)',
          'text-opacity': 1,
          'font-size': 10,
          'font-weight': 600,
          'color': '#ffffff',
          'text-background-color': C.accent,
          'text-background-opacity': 1,
          'text-background-padding': 4,
          'text-background-shape': 'roundrectangle',
          'text-border-width': 0,
        },
      },
      // Focus mode — hover 한 노드의 이웃 밖 요소 페이드
      { selector: 'node.gdim', style: { 'opacity': 0.22 } },
      { selector: 'edge.gdim', style: { 'opacity': 0.07, 'text-opacity': 0 } },
      // supervisor → target 감시 엣지. dim (idle), active, intervening 3 단계.
      {
        selector: 'edge.sup-edge',
        style: {
          'line-style': 'dashed',
          'line-dash-pattern': [3, 5],
          'line-color': C.textDim,
          'opacity': 0.28,
          'width': 1.0,
          'label': '',
          'curve-style': 'unbundled-bezier',
        },
      },
      // active — supervisor 가 현재 감시 중 (큐에 일 있거나 이벤트 있음)
      { selector: 'edge.sup-edge.active', style: {
          'opacity': 0.7, 'width': 1.6, 'line-color': C.warn,
          'line-dash-pattern': [4, 4],
      }},
      // intervening — 방금 nudge / 강제 지시 / 트리거 발생 (10s 내)
      {
        selector: 'edge.sup-edge.intervening',
        style: {
          'opacity': 1, 'width': 2.6, 'line-color': C.accent,
          'line-dash-pattern': [6, 3],
          'line-dash-offset': 0,
        },
      },
      // recent — 최근 30분 내 이벤트 (구조화 supervisor_events 기록).
      // intervening 만큼 강하지 않지만 idle/active 보다 명확히 강조 → 사용자가 어떤
      // 슈퍼바이저가 누구한테 최근 영향 줬는지 한눈에 파악 가능.
      {
        selector: 'edge.sup-edge.recent',
        style: {
          'opacity': 0.92, 'width': 2.2, 'line-color': C.ok || '#10b981',
          'line-dash-pattern': [5, 4],
        },
      },
      // Hover — 엣지 직접 hover 또는 연결된 노드 hover 시 라벨/엣지 강조
      { selector: 'edge.hl', style: {
        'text-opacity': 1,
        'opacity': 1,
        'width': 3,
        'z-index': 999,
      }},
      { selector: 'node.hl', style: {
        'border-width': 5,
        'z-index': 999,
      }},
      {
        selector: 'node:active, edge:active',
        style: { 'overlay-opacity': 0.1 },
      },
    ],
    layout: pickGraphLayout(nodes.length, fullscreen, nodes.some(n => (n.classes || '').indexOf('sup') === 0)),
  });

  // ===== Interactivity =====
  cyInstance.on('tap', 'node.agent', (evt) => openAgent(evt.target.id()));
  cyInstance.on('tap', 'node.sup', (evt) => openAgent(evt.target.id()));
  // 오너 노드 — QA 커뮤니티에서만 clickable (심재빈 = LLM 주도 test user, agent 상세 있음).
  // 일반 커뮤니티의 오너는 실제 사람이라 상세뷰 없음 → 클릭 무반응.
  cyInstance.on('tap', 'node.owner', () => {
    if (COMMUNITY === 'qa') openAgent('test-user-bot');
  });
  cyInstance.on('tap', 'edge', (evt) => {
    const ch = evt.target.data('channel');
    if (ch) openChannel(ch);
  });
  // Hover 강조 — 노드 hover → 연결된 엣지 라벨 표시 / 엣지 hover → 본인 라벨 표시
  cyInstance.on('mouseover', 'node', (evt) => {
    const n = evt.target;
    const isOwner = n.hasClass('owner');
    // 오너 노드: QA 에서만 clickable → 그 외엔 default cursor
    container.style.cursor = (isOwner && COMMUNITY !== 'qa') ? 'default' : 'pointer';
    n.addClass('hl');
    n.connectedEdges().addClass('hl');
    // focus mode — 이웃 밖 요소 페이드 (ego-network 강조)
    cyInstance.elements().not(n.closedNeighborhood()).addClass('gdim');
  });
  cyInstance.on('mouseout', 'node', (evt) => {
    container.style.cursor = 'default';
    cyInstance.elements('.hl').removeClass('hl');
    cyInstance.elements('.gdim').removeClass('gdim');
  });
  cyInstance.on('mouseover', 'edge', (evt) => {
    container.style.cursor = 'pointer';
    evt.target.addClass('hl');
  });
  cyInstance.on('mouseout', 'edge', (evt) => {
    container.style.cursor = 'default';
    evt.target.removeClass('hl');
  });

  // 레이아웃 끝나고 명시적으로 fit — 데스크 비율 유지, 모바일은 더 큰 padding 비율 효과로 zoom-out
  cyInstance.ready(() => {
    const isMobile = window.matchMedia('(max-width: 720px)').matches;
    cyInstance.fit(undefined, fullscreen ? 140 : (isMobile ? 6 : 25));
  });
  // 윈도우 리사이즈 / 회전 시 그래프 자동 리핏
  if (!cyInstance._resizeBound) {
    const _onResize = () => {
      try {
        cyInstance.resize();
        const isMobile = window.matchMedia('(max-width: 720px)').matches;
        cyInstance.fit(undefined, isMobile ? 6 : 25);
      } catch {}
    };
    window.addEventListener('resize', _onResize);
    cyInstance._resizeBound = true;
  }

  // 노드 펄스용 색상 stash. thinking 머스타드 노랑은 따뜻한 아바타 위에 더러워보여서
  // 차분한 accent (indigo)로 통일. speaking 만 cyan 유지 (대비)
  cyInstance.scratch('_thinkingColor', C.accent);
  cyInstance.scratch('_speakingColor', C.speaking);

  // ===== 라이브 엣지 + 노드 펄스 애니메이션 시작 =====
  startLiveEdgeAnimation();
  startNodePulseAnimation();

  // ===== Note (n connections · m nodes · k supervisors) =====
  const noteEl = document.getElementById('graph-note');
  if (noteEl) {
    const supNodeCount = nodes.filter(n => n.classes && n.classes.indexOf('sup') === 0).length;
    const agentNodeCount = nodes.length - supNodeCount;
    const supEdgeCount = edges.filter(e => e.classes && e.classes.indexOf('sup-edge') === 0).length;
    const channelEdgeCount = edges.length - supEdgeCount;
    let txt = `${channelEdgeCount} connection${channelEdgeCount === 1 ? '' : 's'} · ${agentNodeCount} node${agentNodeCount === 1 ? '' : 's'}`;
    if (supNodeCount) txt += ` · ${supNodeCount} supervisor${supNodeCount === 1 ? '' : 's'}`;
    noteEl.textContent = txt;
  }
}

function toggleGraphFullscreen() {
  document.body.classList.toggle('graph-fullscreen');
  lastGraphSig = null;  // 재렌더 강제
  tick();
}
// ESC로 fullscreen 빠져나오기
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && document.body.classList.contains('graph-fullscreen')) {
    document.body.classList.remove('graph-fullscreen');
    tick();
  }
});

// 창 크기 / 패널 크기 변할 때 그래프 재렌더
//   - window resize: 창 크기 바뀜 (기본)
//   - ResizeObserver: 사이드바 토글 등 창 크기 안 변해도 패널 width 변할 때 감지
//   - debounce 로 과도 호출 방지, 같은 크기면 skip
(function() {
  let _resizeTimer = null;
  let _lastStageSize = null;
  function _measureAndMaybeRerender() {
    const panel = document.getElementById('graph-panel');
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    const fs = document.body.classList.contains('graph-fullscreen');
    const key = `${Math.round(rect.width)}x${fs ? 'fs' : 'n'}x${window.innerHeight}`;
    if (key === _lastStageSize) return;
    _lastStageSize = key;
    lastGraphSig = null;
    if (typeof tick === 'function') tick();
  }
  function _schedule() {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(_measureAndMaybeRerender, 180);
  }
  window.addEventListener('resize', _schedule);
  // ResizeObserver — 패널 자체 크기 변경 감지 (브라우저 zoom, sidebar 등)
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(_schedule);
    // panel 은 초기 렌더 후 DOM 에 있음
    document.addEventListener('DOMContentLoaded', () => {
      const p = document.getElementById('graph-panel');
      if (p) ro.observe(p);
    });
    // 이미 로드됐을 수 있으므로
    const p0 = document.getElementById('graph-panel');
    if (p0) ro.observe(p0);
  }

})();

function activeScenes(snap) {
  return (snap.scenes || []).filter(s => s.status === 'active');
}

function firstActiveScene(snap) {
  return activeScenes(snap)[0] || null;
}

// ═══ 타임존 처리 — 모든 서버 타임스탬프는 이 함수들 통해 렌더 ═══
// 서버 규약: UTC aware ISO (`...+00:00` 또는 `...Z`). 마이그레이션 완료 후 기본값.
// 레거시 호환: naive 문자열이 들어오면 T 구분자는 KST, 공백 구분자는 UTC 로 간주.
// 클라이언트가 어느 tz 에 있든 toLocaleString(undefined, ...) 가 브라우저 로컬로 변환.
function _parseServerTs(iso) {
  if (!iso) return null;
  const s = String(iso).trim();
  if (!s) return null;
  const isAware = /Z$|[+\-]\d{2}:?\d{2}$/.test(s);
  if (isAware) return new Date(s);
  // Naive: T 구분자 → KST 로 간주 (Python datetime.now() 레거시)
  //        공백 구분자 → UTC 로 간주 (SQLite CURRENT_TIMESTAMP 레거시)
  const fallback = s.includes('T') ? '+09:00' : '+00:00';
  return new Date(s + fallback);
}

function fmtLocal(iso, opts) {
  const d = _parseServerTs(iso);
  if (!d || isNaN(d.getTime())) return String(iso || '');
  return d.toLocaleString(undefined, opts || {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
}

function fmtLocalDate(iso) {
  const d = _parseServerTs(iso);
  if (!d || isNaN(d.getTime())) return String(iso || '');
  return d.toLocaleDateString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function fmtLocalHM(iso) {
  const d = _parseServerTs(iso);
  if (!d || isNaN(d.getTime())) return String(iso || '');
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
}

function fmtLocalHMS(iso) {
  const d = _parseServerTs(iso);
  if (!d || isNaN(d.getTime())) return String(iso || '');
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

function fmtLocalMonthDayHM(iso) {
  const d = _parseServerTs(iso);
  if (!d || isNaN(d.getTime())) return String(iso || '');
  return d.toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

// 기존 이름 호환
function fmtDateTime(iso) { return fmtLocal(iso); }

function renderSceneCard(s) {
  const statusLabel = {
    active: '진행 중',
    completed: '완료',
    not_started: '시작 전',
  }[s.status] || s.status;
  // 상태 배지 — 좌측 바 없이 틴트 필로만 (design_system §1.1: 왼쪽 색 바 금지)
  const badgeStyle = {
    active: 'background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent)',
    completed: 'background:color-mix(in srgb,var(--ok) 14%,transparent);color:var(--ok)',
    not_started: 'background:var(--panel);color:var(--text-faint)',
  }[s.status] || '';
  // not_started 는 흐릿하게, completed 는 거의 흑백 (차분한 회색) 처리로 "끝난 일" 시각화.
  const dim = s.status === 'not_started' ? 'opacity:0.6;'
            : s.status === 'completed' ? 'opacity:0.55;filter:grayscale(0.7);'
            : '';
  return `<div class="scene-card" style="padding:16px 20px;margin-bottom:10px;background:var(--panel-2);border-radius:12px;${dim}">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <span style="font-size:22px">${s.icon || '🎭'}</span>
      <span style="font-size:15px;font-weight:600;color:var(--text);flex:1">${esc(s.name)}</span>
      <span style="font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;padding:3px 10px;border-radius:999px;${badgeStyle}">${statusLabel}</span>
    </div>
    <div style="color:var(--text-dim);font-size:12px;line-height:1.55;margin-bottom:8px">${esc(s.description)}</div>
    ${s.phase_desc ? `<div style="display:inline-block;padding:3px 8px;background:var(--panel);border-radius:6px;font-size:11px;color:var(--text);font-family:'JetBrains Mono',monospace">${esc(s.phase_desc)}</div>` : ''}
    <div style="display:flex;gap:14px;margin-top:8px;font-size:10.5px;color:var(--text-faint)">
      ${s.started_at ? `<span>시작: <b style="color:var(--text-dim);font-weight:500">${esc(fmtDateTime(s.started_at))}</b></span>` : ''}
      ${s.completed_at ? `<span>완료: <b style="color:var(--ok);font-weight:500">${esc(fmtDateTime(s.completed_at))}</b></span>` : ''}
      ${s.status === 'active' ? '<span style="color:var(--accent)">● LIVE</span>' : ''}
    </div>
  </div>`;
}

function renderScenes(scenes) {
  if (!scenes || !scenes.length) {
    return '<div class="empty">씬 정보 없음</div>';
  }
  const active = scenes.filter(s => s.status === 'active');
  const completed = scenes.filter(s => s.status === 'completed');
  const notStarted = scenes.filter(s => s.status === 'not_started');

  const sec = (title, arr, hint) => arr.length
    ? `<div class="detail-section"${title === 'Active' ? ' style="margin-top:0"' : ''}>
         <h4>${esc(title)} · ${arr.length}</h4>
         ${hint ? `<div style="color:var(--text-dim);font-size:11.5px;margin-bottom:10px">${esc(hint)}</div>` : ''}
         ${arr.map(renderSceneCard).join('')}
       </div>`
    : '';

  // 향후 추가 예정 씬 placeholder (정적)
  const futureHint = `<div class="detail-section">
    <h4>Future Scene Types</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;font-size:12px">
      <div style="padding:10px 14px;background:var(--panel-2);border-radius:8px;opacity:0.5">
        <div style="font-weight:600">🎂 Birthday</div>
        <div style="color:var(--text-dim);font-size:11px">멤버 생일 이벤트 (TBD)</div>
      </div>
      <div style="padding:10px 14px;background:var(--panel-2);border-radius:8px;opacity:0.5">
        <div style="font-weight:600">⚡ Conflict</div>
        <div style="color:var(--text-dim);font-size:11px">멤버간 갈등 씬 (TBD)</div>
      </div>
      <div style="padding:10px 14px;background:var(--panel-2);border-radius:8px;opacity:0.5">
        <div style="font-weight:600">🎉 Party</div>
        <div style="color:var(--text-dim);font-size:11px">단체 모임 씬 (TBD)</div>
      </div>
    </div>
  </div>`;

  return [
    sec('Active', active, '지금 진행 중인 씬'),
    sec('Completed', completed, '이전에 완료된 씬'),
    sec('Not Started', notStarted, '아직 시작 안 된 시나리오'),
    futureHint,
  ].join('');
}

// ==== Achievements ====
function renderAchievements(data) {
  const items = (data && data.items) || [];
  if (!items.length) {
    document.getElementById('ach-grid').innerHTML = '<div class="empty">도전과제 정보 없음</div>';
    document.getElementById('ach-fill').style.width = '0%';
    document.getElementById('ach-pct').textContent = '0 / 0';
    const tc = document.getElementById('tc-achievements');
    if (tc) tc.textContent = '—';
    return;
  }
  const done = data.done || 0;
  const total = data.total || items.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  document.getElementById('ach-fill').style.width = pct + '%';
  document.getElementById('ach-pct').textContent = `${done} / ${total} (${pct}%)`;
  const tc = document.getElementById('tc-achievements');
  if (tc) tc.textContent = `${done}/${total}`;

  // agent_id (e.g. agent-mgr-001) → 이름 매핑. snapshot 의 agents 가 있으면 거기서, 없으면 raw.
  const agentNameById = (id) => {
    if (!id) return '';
    if (typeof window !== 'undefined' && window._lastSnap && Array.isArray(window._lastSnap.agents)) {
      const a = window._lastSnap.agents.find(x => x.id === id);
      if (a) return a.name || id;
    }
    return id;
  };

  const fmtProgress = (p) => {
    if (!p || typeof p !== 'object') return '';
    // 메타 박살 — 누가 박살됐는지 + 시점
    if (p.name && p.at) {
      const when = String(p.at).slice(0, 16).replace('T', ' ');
      return `💀 ${esc(p.name)} (${esc(when)})`;
    }
    // 사랑 도전과제 (mgr_love / persona_love) — 최초 달성 상대 이름 우선
    if ((p.agent || p.agent_name) && (p.owner_msg || p.agent_msg)) {
      const who = p.agent_name || agentNameById(p.agent);
      return `❤️ ${esc(who)}`;
    }
    // 마음 열기 (confession) — 친구가 마음 연 대상 = 그 친구 이름
    if ((p.agent || p.agent_name) && p.message && !p.owner_msg) {
      const who = p.agent_name || agentNameById(p.agent);
      return `💗 ${esc(who)}`;
    }
    if (p.msgs != null && p.need != null) return `${p.msgs} / ${p.need}`;
    if (p.talked_to && p.need) return `${p.talked_to.length} / ${p.need}`;
    if (p.talked_to) return p.talked_to.slice(0, 5).join(', ') + (p.talked_to.length > 5 ? ` +${p.talked_to.length - 5}` : '');
    if (p.channels) return p.channels.slice(0, 3).join(', ');
    if (p.channel) return esc(p.channel);
    if (p.days != null) return `${p.days}일`;
    if (p.friend) return esc(p.friend);
    if (p.description) return esc(String(p.description).slice(0, 40));
    if (p.count != null && p.threshold) return `${p.count} / ${p.threshold}`;
    if (p.count != null) return `${p.count}건`;
    return '';
  };

  document.getElementById('ach-grid').innerHTML = items.map(it => {
    const st = it.state || 'locked';
    const progChip = fmtProgress(it.progress);
    // done/unlocked 상태에서만 클릭 가능 — locked 는 trigger 가 없어서 모달 의미 없음
    const clickable = (st === 'done' || st === 'unlocked');
    const handler = clickable ? `onclick="openAchievementDetail('${esc(it.key)}')"` : '';
    const cursorStyle = clickable ? 'style="cursor:pointer"' : '';
    return `<div class="ach-card ${st}" ${handler} ${cursorStyle} title="${clickable ? '클릭 — trigger 대화 보기' : ''}">
      <div class="ach-icon">${it.icon || '🏅'}</div>
      <div class="ach-body">
        <div class="ach-name">${esc(it.title)}</div>
        <div class="ach-desc">${esc(it.description)}</div>
        ${progChip ? `<div class="ach-progress-chip">${progChip}</div>` : ''}
      </div>
    </div>`;
  }).join('');
}

// 도전과제 상세 모달 — trigger 메시지 + 주변 대화 표시
async function openAchievementDetail(key) {
  if (!key) return;
  const data = await j(q(`/api/achievement_detail?key=${encodeURIComponent(key)}`));
  if (!data || data.error) {
    openModal('🏅', 'Error', `<div class="empty">${esc(data?.error || 'failed to load')}</div>`);
    return;
  }
  const ctx = data.context || [];
  const triggerCh = data.trigger_channel || '';
  let body = '';
  body += `<div style="display:flex;gap:14px;align-items:flex-start;margin-bottom:14px;">
    <div style="font-size:42px;line-height:1">${data.icon || '🏅'}</div>
    <div style="flex:1;min-width:0">
      <div style="font-size:17px;font-weight:700;color:var(--text)">${esc(data.title || key)}</div>
      <div style="font-size:13px;color:var(--text-dim);margin-top:2px">${esc(data.description || '')}</div>
      <div style="font-size:11.5px;color:var(--text-faint);margin-top:6px;font-family:ui-monospace,monospace">
        state: ${esc(data.state || '?')}${data.completed_at ? ' · 완료 ' + fmtAgo(data.completed_at) + ' 전' : ''}
      </div>
    </div>
  </div>`;

  // progress 요약 (key-value)
  const p = data.progress || {};
  const pkeys = Object.keys(p).filter(k => p[k] != null && k !== 'message' && k !== 'description');
  if (pkeys.length) {
    body += `<div class="detail-section"><h4>진척 데이터</h4>
      <div style="font-size:12.5px;line-height:1.7;color:var(--text-dim)">
        ${pkeys.map(k => `<div><b style="color:var(--text)">${esc(k)}</b>: ${esc(typeof p[k] === 'object' ? JSON.stringify(p[k]) : String(p[k]))}</div>`).join('')}
      </div>
    </div>`;
  }

  // trigger 대화 thread
  if (ctx.length) {
    const lines = ctx.map(m => {
      const isTrigger = m.is_trigger;
      const userClass = m.is_owner ? 'user' : '';
      return `<div class="cline ${userClass}" style="${isTrigger ? 'background:color-mix(in srgb,var(--accent) 14%,transparent);border-left:3px solid var(--accent);padding-left:10px;border-radius:6px;margin:4px 0' : 'padding-left:10px;margin:2px 0'}">
        <div style="display:flex;gap:6px;align-items:baseline">
          <b style="color:${m.is_owner ? 'var(--user)' : 'var(--accent)'};font-size:12px">${esc(m.speaker_name)}</b>
          <span style="color:var(--text-faint);font-size:10.5px">${esc(_fmtMsgTime(m.timestamp))}</span>
          ${isTrigger ? '<span style="color:var(--accent);font-size:10px;font-weight:700;letter-spacing:0.5px;margin-left:auto">TRIGGER</span>' : ''}
        </div>
        <div style="font-size:13px;color:var(--text);margin-top:1px;word-break:break-word">${esc(m.message || '')}</div>
      </div>`;
    }).join('');
    body += `<div class="detail-section">
      <h4>${triggerCh ? `📍 #${esc(triggerCh)} 의 대화` : '📍 trigger 대화'}</h4>
      ${lines}
    </div>`;
  } else {
    body += `<div class="detail-section"><h4>대화 컨텍스트 없음</h4>
      <div class="empty">trigger 메시지를 못 찾았어 — 도전과제는 events 테이블이나 다른 source 로 달성됐을 수 있음.</div>
    </div>`;
  }

  openModal(data.icon || '🏅', data.title || key, body);
}

async function loadAchievements() {
  const data = await j(q('/api/achievements'));
  if (data) renderAchievements(data);
}

function syntheticTestUserAgent(snap) {
  // QA 커뮤니티에서만 test-user-bot을 가상 에이전트로 표시
  if (snap.community_id !== 'qa') return null;
  const alive = snap.bot.test_user_alive;
  // .thinking-test-user / .speaking-test-user 플래그를 서버에서 받아 반영
  const thinking = !!snap.bot.test_user_thinking;
  const speaking = !!snap.bot.test_user_speaking;
  return {
    id: 'test-user-bot',
    type: 'persona',
    name: (snap.meta.user_name || 'Test User') + ' (QA)',
    status: alive ? 'active' : 'inactive',
    emotion: alive ? '신남' : '평온',
    emoji: alive ? '🤩' : '😌',
    intensity: alive ? 7 : 0,
    mbti: 'ENTP',
    age: 26,
    last_active: new Date().toISOString(),
    thinking: thinking,
    speaking: speaking,
    thinking_seconds: 0,
    speaking_seconds: 0,
    model: 'claude-haiku-4-5',
    provider: 'claude',
    // model_override 는 false — true 면 .model-tag.override 가 accent 색으로 덮어써서
    // 페르소나 m-haiku 뱃지랑 색깔 안 맞음. test_user 는 default Haiku 라 override 아님.
    model_override: false,
    _synthetic: true,
  };
}

async function tick() {
  // 4개 엔드포인트 병렬 fetch (/api/dev 는 글로벌 admin 으로 이전 — community 단위 fetch 제거)
  const [snap, logs, health, usage] = await Promise.all([
    j(q('/api/snapshot')),
    j(q('/api/logs?tail=200')),
    j(q('/api/health')),
    j(q('/api/usage')),
  ]);
  if (!snap) return;
  // 전역에 snap 캐시 — renderEvent 등 다른 헬퍼가 user_name/agents 조회 시 사용.
  window.__GLIMI_LAST_SNAP__ = snap;

  COMMUNITY = snap.community_id;
  const b = snap.bot, m = snap.meta;

  // 서버 언어 설정 반영 (community_meta.language)
  const prevLang = currentLang();
  SERVER_LANG = (snap.community_meta && snap.community_meta.language) || 'ko';
  const newLang = currentLang();
  if (newLang !== prevLang || !I18N_CACHE[newLang]) {
    await loadLang(newLang);
    applyLangLabel();
  }

  // QA에 test-user 가상 에이전트 추가 (맨 앞)
  const testUser = syntheticTestUserAgent(snap);
  if (testUser) {
    snap.agents = [testUser, ...snap.agents];
  }

  // Empty community 체크 — agents 비어있고 conversations 없으면 초기화되지 않은 상태
  const hasData = (snap.agents && snap.agents.length > 0) || snap.total_messages > 0;
  document.body.classList.toggle('community-empty', !hasData);
  const ecid = document.getElementById('empty-cid');
  if (ecid) ecid.textContent = snap.community_id;

  // Offline 모드 토글 — 봇이 실제로 안 돌면 전체 UI dim + 안내
  if (b.bot_alive) document.body.classList.remove('offline');
  else document.body.classList.add('offline');

  // 마지막 활동 시각 계산 (에이전트 last_active 중 최대값)
  const lastActives = snap.agents.map(a => a.last_active).filter(Boolean).sort();
  if (!b.bot_alive && lastActives.length) {
    const last = lastActives[lastActives.length - 1];
    document.getElementById('offline-last').textContent = `마지막 활동: ${fmtLocal(last)}`;
  } else {
    document.getElementById('offline-last').textContent = '';
  }

  // 헤더 pills/meta는 제거됨 — 모든 정보는 KPI 카드에 있음

  document.getElementById('tc-agents').textContent = snap.agents.length;
  document.getElementById('tc-channels').textContent = snap.channels.length;
  document.getElementById('tc-messages').textContent = snap.recent_messages.length;
  document.getElementById('tc-scenes').textContent = (snap.scenes || []).filter(s => s.status === 'active').length;
  document.getElementById('tc-events').textContent = snap.events.length;

  // Dev pending 배지 — supervisor view 토글 ON + pending 1+ 일 때만 (모든 커뮤니티 통일)
  const devBadge = document.getElementById('dev-pending-badge');
  if (devBadge) {
    if (SHOW_SUP && (snap.dev_pending_count || 0) > 0) {
      const linkHref = `/admin/dev-requests?community=${encodeURIComponent(snap.community_id || '')}`;
      devBadge.href = linkHref;
      document.getElementById('dev-pending-count').textContent = snap.dev_pending_count;
      devBadge.style.display = 'inline-flex';
    } else {
      devBadge.style.display = 'none';
    }
  }
  const supActiveCount = (snap.supervisors || []).filter(s => s.active).length;
  const supEl = document.getElementById('tc-supervisors');
  if (supEl) supEl.textContent = supActiveCount;
  // Supervisors 탭 렌더
  const supFull = document.getElementById('supervisors-full');
  if (supFull) supFull.innerHTML = renderSupervisorsTab(snap.supervisors || []);

  // 확장된 agent들 로그+채팅 추가 fetch
  const active = snap.agents.filter(a => a.thinking || a.speaking);
  if (active.length) {
    await Promise.all(active.map(async (a) => {
      const extra = await j(q(`/api/agent_activity?id=${encodeURIComponent(a.id)}`));
      if (extra) { a._logs = extra.logs || []; a._chat = extra.chat || []; }
    }));
  }

  // Hero section
  document.getElementById('hero').innerHTML = renderHero(snap);

  // Overview KPIs
  // Server Status = 서버 전체 살아있는지 (bot alive 기반)
  document.getElementById('kpi-server').innerHTML = b.bot_alive
    ? `<span style="color:var(--ok)">● Online</span>`
    : `<span style="color:var(--err)">○ Offline</span>`;
  document.getElementById('kpi-bot').innerHTML = b.bot_alive
    ? `<span style="color:var(--ok)">● Running</span>`
    : `<span style="color:var(--err)">○ Stopped</span>`;
  document.getElementById('kpi-user').innerHTML = esc(m.user_name || '—');
  // Active Scene: 현재 진행 중 씬 (snap.scenes에서 status='active' 첫번째)
  const scene = firstActiveScene(snap);
  const actives = activeScenes(snap);
  document.getElementById('kpi-scene').innerHTML = scene
    ? `<span style="color:var(--accent)">${esc(scene.icon || '')} ${esc(scene.name)}</span><small>${esc(scene.phase_desc || scene.status)}${actives.length > 1 ? ` +${actives.length - 1}` : ''}</small>`
    : `<span style="color:var(--text-faint);font-size:15px">—</span><small>nothing active</small>`;
  document.getElementById('kpi-msgs').innerHTML = `${snap.total_messages}<small>total</small>`;

  // Connection Graph — 구조 변화 있을 때만 재렌더 (깜빡임 방지)
  //   동일 구조면 live 상태만 DOM 레벨로 업데이트
  const graphEl = document.getElementById('graph-panel');
  if (graphEl) {
    const sig = graphSignature(snap);
    if (sig !== lastGraphSig) {
      graphEl.innerHTML = renderConnectionGraph(snap);
      mountCytoscapeGraph(snap);
      lastGraphSig = sig;
    } else {
      // 구조 동일 → 노드 thinking/speaking 클래스만 갱신
      updateGraphLiveState(snap);
    }
  }

  // dev agent (한세나) — supervisor view 토글 ON 일 때만 카드 표시 (모든 커뮤니티 통일).
  const visibleAgents = SHOW_SUP ? snap.agents : snap.agents.filter(a => a.type !== 'dev');

  // 에이전트 리스트 — 시그니처 변화 또는 활동 중(라이브 카운터/로그)일 때만 재렌더.
  //   overview·full 은 같은 데이터 → HTML 1회 생성해 둘 다 주입.
  // offline 이면 thinking/speaking 은 stale (봇 죽었는데 DB 플래그 잔존) → 활동 아님으로 취급
  const anyActive = b.bot_alive && snap.agents.some(a => a.thinking || a.speaking);
  const aSig = (SHOW_SUP ? 'S|' : '') + agentsSignature(visibleAgents);
  if (anyActive || aSig !== lastAgentsSig) {
    const agHtml = visibleAgents.map(a => renderAgent(a)).join('') || '<div class="empty">no members</div>';
    document.getElementById('overview-agents').innerHTML = agHtml;
    document.getElementById('agents-full').innerHTML = agHtml;
    lastAgentsSig = aSig;
  }

  // 메시지 — 새 메시지 있을 때만 재렌더 (스크롤 위치 보존)
  const ovMsgs = document.getElementById('overview-msgs');
  const fm = document.getElementById('messages-full');
  const mSig = messagesSignature(snap.recent_messages);
  if (mSig !== lastMsgSig) {
    const keepOv = atBottom(ovMsgs), keepFm = atBottom(fm);
    ovMsgs.innerHTML = snap.recent_messages.slice(-10).map(renderMessage).join('') || '<div class="empty">no conversations yet</div>';
    fm.innerHTML = snap.recent_messages.map(renderMessage).join('') || '<div class="empty">no conversations yet</div>';
    if (keepOv) ovMsgs.scrollTop = ovMsgs.scrollHeight;
    if (keepFm) fm.scrollTop = fm.scrollHeight;
    lastMsgSig = mSig;
  }

  // 채널 — 구조/카운트 변화 시만
  const chSig = channelsSignature(snap.channels);
  if (chSig !== lastChannelsSig) {
    document.getElementById('channels-full').innerHTML = renderChannelsGrouped(snap.channels);
    lastChannelsSig = chSig;
  }
  // Scenes 탭: 각 씬 카드 (active/completed/not_started 상태별 스타일)
  const scenesEl = document.getElementById('scenes-full');
  if (scenesEl) {
    const scenes = snap.scenes || [];
    scenesEl.innerHTML = renderScenes(scenes);
  }

  // Events 탭: events 테이블 — 발생한 일들의 로그 (멤버간 사건 기록)
  const eventsEl = document.getElementById('events-full');
  if (eventsEl) {
    eventsEl.innerHTML = snap.events.length
      ? `<div style="color:var(--text-dim);font-size:11.5px;margin-bottom:12px">
           커뮤니티에서 발생한 사건 기록 — 관계 변화, 갈등, 화해 등 persona들의 내면 이벤트
         </div>` + snap.events.map(renderEvent).join('')
      : '<div class="empty">기록된 이벤트 없음</div>';
  }

  // Health
  if (health) {
    const diskPct = health.disk_total_bytes ? (health.disk_used_bytes / health.disk_total_bytes * 100).toFixed(1) : 0;
    const memPct = health.sys_mem_pct || 0;
    const glimiMemPct = health.sys_mem_total_bytes ? (health.glimi_mem_bytes / health.sys_mem_total_bytes * 100).toFixed(1) : 0;
    const serverRun = health.bot_alive;
    // Server Control 은 플랫폼 상단 바로 이동됨 — Health 탭은 순수 health 정보만
    document.getElementById('health-full').innerHTML = `
      <div style="margin-bottom:18px">
        <div class="section-title" style="margin-top:0">Processes</div>
        <div class="health-grid">
          <div class="health-card">
            <h4>Discord Bot</h4>
            <div class="big">${health.bot_alive ? '<span style="color:var(--ok)">● Running</span>' : '<span style="color:var(--err)">○ Stopped</span>'}</div>
            ${health.pid ? `<div class="sub">PID: ${esc(health.pid)}</div>` : ''}
          </div>
          <div class="health-card">
            <h4>QA Runner</h4>
            <div class="big">${health.runner_alive ? '<span style="color:var(--ok)">● Active</span>' : '<span style="color:var(--text-faint)">○ Idle</span>'}</div>
            <div class="sub">${health.test_user_alive ? 'test-user bot alive' : ''}</div>
          </div>
          <div class="health-card">
            <h4>Dev Mode</h4>
            <div class="big">${health.dev_active ? '<span style="color:var(--warn)">● Active</span>' : '<span style="color:var(--text-faint)">○ Off</span>'}</div>
          </div>
        </div>
      </div>

      <div style="margin-bottom:18px">
        <div class="section-title" style="margin-top:0">Glimi Resource Usage</div>
        <div class="health-grid">
          <div class="health-card">
            <h4>CPU (Glimi procs)</h4>
            <div class="big">${health.glimi_cpu_pct.toFixed(1)}<small style="font-size:13px;color:var(--text-dim)">%</small></div>
            <div class="sub">${health.glimi_proc_count} process${health.glimi_proc_count === 1 ? '' : 'es'}</div>
          </div>
          <div class="health-card">
            <h4>RAM (Glimi procs)</h4>
            <div class="big">${fmtBytes(health.glimi_mem_bytes)}</div>
            <div class="sub">${glimiMemPct}% of system RAM</div>
            <div class="disk-bar"><span style="width:${Math.min(100, parseFloat(glimiMemPct))}%"></span></div>
          </div>
          <div class="health-card">
            <h4>DB Size</h4>
            <div class="big">${fmtBytes(health.db_size_bytes)}</div>
            <div class="sub">community SQLite</div>
          </div>
        </div>
      </div>

      <div style="margin-bottom:18px">
        <div class="section-title" style="margin-top:0">System Resources</div>
        <div class="health-grid">
          <div class="health-card">
            <h4>System CPU</h4>
            <div class="big">${health.sys_cpu_pct.toFixed(1)}<small style="font-size:13px;color:var(--text-dim)">%</small></div>
            <div class="sub">load: ${health.sys_load_1m} / ${health.sys_load_5m} / ${health.sys_load_15m}</div>
            <div class="disk-bar"><span style="width:${Math.min(100, health.sys_cpu_pct)}%"></span></div>
          </div>
          <div class="health-card">
            <h4>System RAM</h4>
            <div class="big">${fmtBytes(health.sys_mem_used_bytes)} <small style="font-size:12px;color:var(--text-dim)">/ ${fmtBytes(health.sys_mem_total_bytes)}</small></div>
            <div class="sub">${memPct}% used</div>
            <div class="disk-bar"><span style="width:${memPct}%"></span></div>
          </div>
          ${renderGpuCard(health.gpu, health.sys_mem_total_bytes, health.sys_mem_used_bytes)}
          <div class="health-card">
            <h4>Disk</h4>
            <div class="big">${fmtBytes(health.disk_used_bytes)} <small style="font-size:12px;color:var(--text-dim)">/ ${fmtBytes(health.disk_total_bytes)}</small></div>
            <div class="sub">free: ${fmtBytes(health.disk_free_bytes)} · ${diskPct}% used</div>
            <div class="disk-bar"><span style="width:${diskPct}%"></span></div>
          </div>
        </div>
      </div>
    `;
    // Server Control 은 플랫폼 상단 바로 이관됨 — Health 탭에는 server-log 없음
  }

  // Sync tab — sync-output 의 기존 로그 보존 (재렌더 시 사용자가 방금 본 sync 진행 안 지워지게).
  const serverRunning = b.bot_alive;
  const guardNote = serverRunning
    ? `<div style="padding:10px 14px;background:color-mix(in srgb,var(--accent) 10%,var(--panel));border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);border-radius:10px;margin-bottom:16px;font-size:12px;color:var(--text)">ℹ 서버 실행 중 — Sync 버튼 클릭 시 <b>자동으로 서버 중단 → 작업 → 재시작</b> 진행. 취소 버튼 제공됨.</div>`
    : `<div style="padding:10px 14px;background:color-mix(in srgb,var(--ok) 8%,var(--panel));border:1px solid color-mix(in srgb,var(--ok) 25%,transparent);border-radius:10px;margin-bottom:16px;font-size:12px;color:var(--ok)">○ 서버 오프라인 — 모든 sync 작업 즉시 가능.</div>`;
  const _prevSyncOutput = document.getElementById('sync-output');
  const _savedSyncLog = _prevSyncOutput ? _prevSyncOutput.textContent : '';
  document.getElementById('sync-full').innerHTML = `
    ${guardNote}
    <div class="detail-section" style="margin-top:0">
      <h4>Sync Actions</h4>
      <div style="color:var(--text-dim);font-size:11.5px;margin-bottom:10px">
        Discord 서버와 DB 사이 상태를 맞추는 작업. 서버 실행 중이면 자동 중단·작업·재시작.
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
        <button class="act-btn primary" onclick="runSyncAction('scan')">🔍 Scan Discord</button>
        <button class="act-btn success" onclick="runSyncAction('sync')" title="전체 채널 싱크 (스캔 없이)">▶ Full Sync</button>
        <button class="act-btn" onclick="runSyncAction('arrange')" title="카테고리·채널 순서만 정렬 (빠름)">⇅ 채널 순서 정렬</button>
        <button class="act-btn" onclick="runSyncAction('restore')">↻ Restore Messages</button>
      </div>
      <div id="scan-result" style="margin-bottom:12px"></div>
      <div id="sync-output" style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-dim);background:var(--panel-2);padding:10px;border-radius:8px;min-height:60px;max-height:180px;overflow-y:auto;white-space:pre-wrap"></div>
    </div>
    <div class="detail-section">
      <h4>Trash · <span id="trash-count" style="color:var(--text-faint)">...</span></h4>
      <div style="color:var(--text-dim);font-size:11.5px;margin-bottom:10px">
        휴지통 — 채널/메시지 삭제 시 완전 삭제 대신 여기로 옮겨짐. 실수 복구용 안전망.
        <br>Empty Trash 로 영구 삭제, 각 항목별 <b>복구</b> 가능.
      </div>
      <div style="display:flex;gap:8px;margin-bottom:10px">
        <button class="act-btn small" onclick="loadTrash()">새로고침</button>
        <button class="act-btn small danger" onclick="emptyTrash()">Empty Trash</button>
      </div>
      <div id="trash-list"></div>
    </div>
    <div class="detail-section">
      <h4>DB-registered Channels · ${(snap.channels || []).length}</h4>
      ${renderChannelsGrouped(snap.channels || [])}
    </div>
  `;
  if (_savedSyncLog) {
    document.getElementById('sync-output').textContent = _savedSyncLog;
  }
  // Scan 결과 테이블 복원 (tick 마다 사라지지 않도록)
  renderScanTable();
  loadTrash();

  // (legacy "Dev" tab 제거됨 — 새 글로벌 admin 페이지 /admin/dev-requests 로 이전)

  // Usage — telemetry parsed
  if (usage) {
    if (usage.source !== 'telemetry') {
      document.getElementById('usage-full').innerHTML = `
        <div class="detail-section">
          <h4>Usage</h4>
          <div style="color:var(--text-dim);font-size:13px">
            telemetry 데이터 없음 — ~/.claude/telemetry 파일 찾지 못함.<br>
            로그 기반 근사치: sonnet ${usage.sonnet_calls || 0} · haiku ${usage.haiku_calls || 0} · opus ${usage.opus_calls || 0}
          </div>
        </div>`;
    } else {
      const dayBars = (usage.recent_days || []).slice().reverse();
      const maxDay = Math.max(...dayBars.map(d => d.cost), 0.01);
      const totalTokens = usage.tokens_input + usage.tokens_output + usage.tokens_cache_write + usage.tokens_cache_read;
      const apiMin = (usage.api_duration_ms / 1000 / 60).toFixed(1);
      const modelRows = Object.entries(usage.by_model || {})
        .sort((a,b) => b[1] - a[1])
        .slice(0, 8)
        .map(([m, c]) => {
          const provider = m.startsWith('claude-') ? 'claude' : (m.includes('gpt') ? 'openai' : 'other');
          return `<div class="rel-row"><span class="rname">${esc(m)}</span><span class="model-tag ${provider}">${c} events</span></div>`;
        }).join('');

      document.getElementById('usage-full').innerHTML = `
        <div class="overview-grid">
          <div class="kpi">
            <div class="label">Total Cost</div>
            <div class="value">$${usage.cost_total_usd.toFixed(2)}<small>${usage.sessions_total} sessions</small></div>
          </div>
          <div class="kpi">
            <div class="label">Today</div>
            <div class="value">$${usage.cost_today_usd.toFixed(2)}</div>
          </div>
          <div class="kpi">
            <div class="label">7-day</div>
            <div class="value">$${usage.cost_week_usd.toFixed(2)}</div>
          </div>
          <div class="kpi">
            <div class="label">30-day</div>
            <div class="value">$${usage.cost_month_usd.toFixed(2)}</div>
          </div>
          <div class="kpi">
            <div class="label">Subscription</div>
            <div class="value" style="font-size:15px">${esc(usage.subscription_type)}</div>
          </div>
        </div>

        <div class="detail-section">
          <h4>Recent 7 Days</h4>
          <div style="display:flex;align-items:flex-end;gap:8px;height:120px;padding:10px 0">
            ${dayBars.map(d => {
              const h = maxDay ? Math.max(3, (d.cost / maxDay * 100)) : 3;
              return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px">
                <div style="font-size:10px;color:var(--text-dim)">${d.cost > 0 ? '$' + d.cost.toFixed(2) : ''}</div>
                <div style="width:100%;height:${h}%;background:linear-gradient(180deg,var(--accent),var(--accent-2));border-radius:4px 4px 0 0;min-height:2px"></div>
                <div style="font-size:10px;color:var(--text-faint)">${d.date.slice(5)}</div>
                <div style="font-size:9px;color:var(--text-faint)">${d.sessions}s</div>
              </div>`;
            }).join('')}
          </div>
        </div>

        <div class="detail-section">
          <h4>Token Usage (All Time)</h4>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:6px">
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Input</div><div style="font-size:16px;font-weight:700">${usage.tokens_input.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Output</div><div style="font-size:16px;font-weight:700">${usage.tokens_output.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Cache Write</div><div style="font-size:16px;font-weight:700">${usage.tokens_cache_write.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Cache Read</div><div style="font-size:16px;font-weight:700">${usage.tokens_cache_read.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Total</div><div style="font-size:16px;font-weight:700">${totalTokens.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">API Time</div><div style="font-size:16px;font-weight:700">${apiMin} min</div></div>
          </div>
        </div>

        ${modelRows ? `<div class="detail-section"><h4>Models</h4>${modelRows}</div>` : ''}

        <div class="detail-section">
          <h4>Source</h4>
          <div style="color:var(--text-dim);font-size:12px">
            ~/.claude/telemetry/ tengu_exit 이벤트 기반 실시간 집계. Claude Code 세션이 종료될 때마다 업데이트됨.
          </div>
        </div>
      `;
    }
  }

  // Logs
  if (logs && logs.lines) {
    const logEl = document.getElementById('logs-full');
    const keepLog = atBottom(logEl);
    logEl.innerHTML = logs.lines.map(l => `<div class="log-line ${classifyLog(l)}">${esc(l)}</div>`).join('') || '<div class="empty">(log empty)</div>';
    if (keepLog) logEl.scrollTop = logEl.scrollHeight;
  }
}

async function loadCommunities() {
  const d = await j('/api/communities');
  if (!d) return;
  // 플랫폼 API 는 list 직접 반환 (계정별 접근 가능한 커뮤니티만).
  // 레거시 {items, active} envelope 도 호환.
  const items = Array.isArray(d) ? d : (d.items || []);
  const active = Array.isArray(d) ? COMMUNITY : d.active;
  const btn = document.getElementById('community-btn');
  const menu = document.getElementById('community-menu');
  if (!btn || !menu) return;
  const activeItem = items.find(c => c.id === active);

  // 버튼 업데이트 (현재 선택된 커뮤니티 이름 우선)
  const displayName = activeItem && (activeItem.name || activeItem.id) || active || '—';
  document.getElementById('community-btn-name').textContent = displayName;
  if (activeItem && activeItem.running) btn.classList.remove('stopped');
  else btn.classList.add('stopped');

  // 메뉴 생성 — 이름 큰 글씨, id 는 작은 mono 로 보조 표시
  menu.innerHTML = items.map(c => {
    const cls = ['ci'];
    if (c.id === active) cls.push('active');
    if (!c.running) cls.push('stopped');
    const ageText = c.last_log_age_sec != null
      ? (c.last_log_age_sec < 60 ? `${c.last_log_age_sec}s` : c.last_log_age_sec < 3600 ? `${Math.floor(c.last_log_age_sec/60)}m` : `${Math.floor(c.last_log_age_sec/3600)}h`) + ' ago'
      : '';
    const meta = c.running
      ? `<span class="ci-meta" style="color:var(--ok)">● running${ageText ? ` · ${ageText}` : ''}</span>`
      : `<span class="ci-meta">○ stopped${ageText ? ` · ${ageText}` : ''}</span>`;
    const nm = esc(c.name || c.id);
    const idBadge = (c.name && c.name !== c.id)
      ? `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-faint);margin-left:4px">${esc(c.id)}</span>`
      : '';
    return `<div class="${cls.join(' ')}" data-cid="${esc(c.id)}">
      <span class="ci-dot"></span>
      <div style="flex:1">
        <div class="ci-name" style="font-family:inherit">${nm}${idBadge}</div>
        ${meta}
      </div>
      <span class="ci-check"></span>
    </div>`;
  }).join('') || '<div class="empty">no communities</div>';

  // 아이템 클릭 → 플랫폼 경로로 이동 (/community/{id}).
  // 페이지 전환이라 state 가 깨끗이 리셋됨 (캐시 leak 없음).
  menu.querySelectorAll('.ci').forEach(el => {
    el.addEventListener('click', () => {
      const newCid = el.dataset.cid;
      if (newCid === COMMUNITY) { menu.classList.remove('open'); return; }
      document.body.classList.add('switching');
      location.href = '/community/' + encodeURIComponent(newCid);
    });
  });
}

// 버튼 클릭으로 메뉴 토글
document.getElementById('community-btn').addEventListener('click', (e) => {
  e.stopPropagation();
  document.getElementById('community-menu').classList.toggle('open');
});
document.addEventListener('click', (e) => {
  const wrap = document.getElementById('community-switcher-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('community-menu').classList.remove('open');
  }
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

// 초기 i18n 프리로드 → 첫 tick → 주기적 갱신
(async () => {
  await loadLang('ko');
  await loadLang('en');
  applyLangLabel();
  await loadCommunities();
  await tick();
  // ?openAgent=ID — auto-open agent modal (used for screenshot capture)
  const _params = new URLSearchParams(location.search);
  const _autoOpen = _params.get('openAgent');
  if (_autoOpen) setTimeout(() => openAgent(_autoOpen), 500);
})();
setInterval(tick, 1500);
setInterval(loadCommunities, 5000);  // 커뮤니티 running 상태 5초마다 갱신
setInterval(loadAchievements, 10000);  // 도전과제 진척도 10초마다 갱신 (탭 카운트 포함)
loadAchievements();  // 최초 1회

// 모바일 브라우저는 백그라운드 탭/화면 잠금 시 setInterval 을 freeze 함.
// 탭 복귀·bfcache 복귀 즉시 폴링 한 바퀴 돌려서 stale 화면 방지.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    tick();
    loadCommunities();
    loadAchievements();
  }
});
window.addEventListener('pageshow', () => {
  tick();
  loadCommunities();
  loadAchievements();
});
