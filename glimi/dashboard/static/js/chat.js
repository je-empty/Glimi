// Glimi Web Chat — production render layer (vanilla JS, dashboard.js style).
//
// Data flow is PRESERVED from Phase 2: channel list (/chat/channels), history
// cold-load (/chat/history), a single WebSocket re-connected per selected
// channel, and frame handling (text/typing/image/interrupted/error/pong). What
// changed is the RENDER layer: Discord-paradigm grouped rows (consecutive
// messages by the same author within a 5-min window collapse to lead + cont
// rows), the owner's own messages render LEFT like everyone (tagged .me), a
// 2-tier contenteditable composer with reply-cue + char count + Shift+Enter,
// gated pinned-autoscroll, an in-stream breathing-dots typing row at the reply
// landing spot, and a lightweight client-side thread view.
//
// REACTIONS + THREADS — now REAL end-to-end (backend phases 1-3 + the chat.py
// wiring landed). The reply action sets a composer reply-cue and the WS text
// frame carries `reply_to:<msgId>`; the backend persists it (reply pointer
// backfilled onto the human turn) and returns it on /chat/history, so replies
// survive reload. Reactions are sent as `add_reaction`/`remove_reaction` frames
// and broadcast back as `reaction`/`reaction_removed` (rendered optimistically,
// reconciled on the authoritative broadcast count). The thread panel fetches the
// REAL thread (`fetch_thread` → `thread` frame) instead of client-only grouping.
// Outbound `text`/`image` frames now carry a persisted `id` so rows are
// anchorable; the owner turn is rendered optimistically and reconciled by
// `client_msg_id` on the broadcast echo.
(function () {
  'use strict';

  // ==== State (injected by template, URL fallback) ====
  // Canonical chat client shared by every Glimi app (Community + Workspace),
  // shipped from glimi/dashboard. The app it runs in is detected from WS_BASE:
  //   • Community  → WS_BASE === ''   → APIs at /community/{cid}/...
  //   • Workspace  → WS_BASE === '/w/{id}' (window.__GLIMI_WS_BASE__ / [data-ws-base])
  // Only apiBase()/avatarUrl() + a couple of owner-label defaults branch on it;
  // everything else is identical, so the two apps can never drift again.
  var params = new URLSearchParams(location.search);
  var WS_BASE = (window.__GLIMI_WS_BASE__ ||
    (document.body && document.body.getAttribute('data-ws-base')) || '')
    .replace(/\/+$/, '');
  var COMMUNITY = window.__GLIMI_COMMUNITY__ || params.get('community') || '';
  var CHANNEL = window.__GLIMI_CHANNEL__ || params.get('channel') || '';
  var AGENT = window.__GLIMI_AGENT__ || params.get('agent') || 'mgr';
  var OWNER_NAME = window.__GLIMI_USER__ || (WS_BASE ? 'You' : 'Me');
  // Look-only mockup (demo): composer stays disabled + a banner shows. The WS
  // backend also rejects writes ('demo_readonly') — this is the UI half.
  var READONLY = window.__GLIMI_READONLY__ === true;
  // Embedded (dashboard #view-chat) vs standalone (/chat). Embedded does NOT
  // auto-boot at load — the dashboard lazy-inits on first Chat-tab entry so the
  // WS isn't opened until the tab is actually shown. Standalone auto-boots.
  var EMBEDDED = !!window.__GLIMI_EMBEDDED__;

  // Theme: canonical platform key 'glimi-theme' (base.html FOUC guard +
  // toggleTheme() own this; this read is redundant-but-harmless, kept for
  // consistency with dashboard.js).
  var THEME = localStorage.getItem('glimi-theme') || 'light';
  document.documentElement.setAttribute('data-theme', THEME);

  // ==== DOM ====
  var $shell = document.getElementById('chat-shell');
  var $sidebar = document.getElementById('chat-sidebar');
  var $sidebarToggle = document.getElementById('chat-sidebar-toggle');
  var $scrim = document.getElementById('chat-scrim');
  var $sideSub = document.getElementById('chat-side-sub');
  var $sideRefresh = document.getElementById('chat-side-refresh');
  var $channelList = document.getElementById('chat-channel-list');
  var $search = document.getElementById('chat-search');
  var $status = document.getElementById('chat-status');
  var $headIcon = document.getElementById('chat-head-icon');
  var $channelLabel = document.getElementById('chat-channel-label');
  var $headTopic = document.getElementById('chat-head-topic');
  var $feed = document.getElementById('chat-feed');
  var $stream = document.getElementById('chat-stream');
  var $typefoot = document.getElementById('chat-typefoot');
  var $typefootWho = document.getElementById('chat-typefoot-who');
  var $cbox = document.getElementById('chat-cbox');
  var $input = document.getElementById('chat-input');
  var $send = document.getElementById('chat-send');
  var $cnt = document.getElementById('chat-cnt');
  var $readonlyBanner = document.getElementById('chat-readonly-banner');
  var $replyCue = document.getElementById('chat-reply-cue');
  var $replyCueText = document.getElementById('chat-reply-cue-text');
  var $replyCueClear = document.getElementById('chat-reply-cue-clear');
  // thread panel
  var $threadToggle = document.getElementById('chat-thread-toggle');
  var $threadPanel = document.getElementById('chat-thread-panel');
  var $threadClose = document.getElementById('chat-thread-close');
  var $threadSub = document.getElementById('chat-thread-sub');
  var $threadBody = document.getElementById('chat-thread-body');
  var $threadFoot = document.getElementById('chat-thread-foot');

  var ws = null;
  var channels = [];

  var MAX_LEN = 2000;
  var CNT_REVEAL = 1500;     // reveal the char counter past this
  var CNT_WARN = 1950;       // counter turns red at/after this
  var GROUP_WINDOW = 5 * 60 * 1000;  // 5 min grouping window

  // ==== Per-channel render bookkeeping ====
  // Grouping state for the live stream.
  var lastRow = null;        // { speakerId, ts, dateKey, groupBody }
  var msgCounter = 0;        // local id source for frame-born messages
  // Message index for this channel render (id → {speakerId, name, text, ...}).
  var msgIndex = {};
  // Reply target captured from a message's reply action.
  var replyTo = null;        // { id, speaker, text }
  // Thread panel state.
  var openThreadRootId = null;
  var lastFocused = null;
  // Session-local unread counts per channel (no backend support).
  var unread = {};
  // In-stream typing rows keyed by speakerId.
  var typingRows = {};
  // Optimistic owner bubbles awaiting their broadcast echo, keyed by client_msg_id.
  var pendingByClientId = {};
  // Default emoji for the one-tap reaction affordance (positive signal — matches
  // the kernel's POSITIVE_REACTION_EMOJI so it feeds the relationship layer).
  var DEFAULT_EMOJI = '❤️';
  // The owner's resolved speaker id (filled from history is_user rows) so the
  // optimistic reaction "mine" state matches the actor the server records.
  var OWNER_ID = null;
  // The last reaction WE initiated, so its broadcast echo can bind OWNER_ID
  // ({id, emoji}); cleared once consumed.
  var pendingReaction = null;

  // ==== Small helpers ====
  // XSS-safe: textContent escape, then rich() only re-introduces known spans.
  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }
  // rich() runs on ALREADY-escaped text (esc first). Only @mention / #channel /
  // <em> markers are turned back into spans — nothing else is un-escaped.
  function rich(s) {
    return s
      .replace(/&lt;em&gt;([^]*?)&lt;\/em&gt;/g, '<em>$1</em>')
      .replace(/@([가-힣A-Za-z0-9_]+)/g, '<span class="mention">@$1</span>')
      .replace(/(^|\s)#([가-힣A-Za-z0-9_\-]+)/g, '$1<span class="ch">#$2</span>');
  }
  function escAttr(s) {
    return esc(s).replace(/"/g, '&quot;');
  }

  function apiBase() {
    // Workspace: per-workspace prefix (/w/{id}/chat). Community: /community/{cid}/chat.
    return WS_BASE
      ? WS_BASE + '/chat'
      : '/community/' + encodeURIComponent(COMMUNITY) + '/chat';
  }
  function avatarUrl(agentId) {
    // Workspace serves avatars per-workspace; Community keys them by community.
    // Append the asset version (when the app injects __GLIMI_ASSET_VER__) so a
    // returning visitor never gets a STALE cached avatar after the route's output
    // changes (e.g. anime portrait → role monogram).
    var ver = (typeof window !== 'undefined' && window.__GLIMI_ASSET_VER__)
      ? '&v=' + encodeURIComponent(window.__GLIMI_ASSET_VER__) : '';
    return WS_BASE
      ? WS_BASE + '/api/avatar?id=' + encodeURIComponent(agentId) + ver
      : '/api/avatar?id=' + encodeURIComponent(agentId) +
        (COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : '') + ver;
  }

  function initialOf(name) {
    var s = (name || '').trim();
    return s ? s.charAt(0).toUpperCase() : '·';
  }
  function avBg(seed) {
    var n = 0, str = String(seed || '');
    for (var i = 0; i < str.length; i++) n = (n + str.charCodeAt(i)) % 4;
    return 'var(--chat-av-' + (n + 1) + ')';
  }
  function parseTs(ts) {
    if (!ts) return Date.now();
    var d = new Date(ts);
    var t = d.getTime();
    return isNaN(t) ? Date.now() : t;
  }
  function dateKeyOf(ms) {
    var d = new Date(ms);
    return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
  }
  function clockOf(ms) {
    try {
      // 'en-US' (not the browser default) so chat chrome stays English even in a
      // Korean-locale browser — matches the rest of the English UI chrome.
      return new Date(ms).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    } catch (e) { return ''; }
  }
  function dayLabelOf(ms) {
    try {
      return new Date(ms).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
    } catch (e) { return ''; }
  }
  function relTime(ms) {
    var diff = Date.now() - ms;
    if (diff < 60000) return 'now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h';
    if (diff < 172800000) return 'yesterday';
    return Math.floor(diff / 86400000) + 'd';
  }

  // Role tag for the active channel's type (DM) / owner.
  function activeChannelType() {
    var c = channels.filter(function (x) { return x.channel === CHANNEL; })[0];
    return c ? (c.type || '') : '';
  }
  function tagFor(isUser, speakerId) {
    if (isUser) return { cls: 'self', label: 'You' };
    // For DM channels the responding agent's type drives the tag.
    if (CHANNEL.indexOf('dm-') === 0 && speakerId === AGENT) {
      if (activeChannelType() === 'mgr') return { cls: 'mgr', label: 'Manager' };
    }
    return null;
  }

  // ==== Pinned autoscroll (gated) ====
  var pinned = true;
  $feed.addEventListener('scroll', function () {
    pinned = ($feed.scrollHeight - $feed.scrollTop - $feed.clientHeight) < 90;
  });
  function stick() { if (pinned) $feed.scrollTop = $feed.scrollHeight; }

  function appear(node) {
    node.classList.remove('in');
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { node.classList.add('in'); stick(); });
    });
  }

  // ==== Avatar markup ====
  function avHtml(speakerId, name, isUser, cls) {
    cls = cls || 'av';
    if (isUser) {
      return '<span class="' + cls + '" style="background:' + avBg(OWNER_NAME) + '">' + esc(initialOf(OWNER_NAME)) + '</span>';
    }
    if (speakerId) {
      return '<span class="' + cls + '" style="background:' + avBg(speakerId) + '">' +
        '<img src="' + escAttr(avatarUrl(speakerId)) + '" alt="" ' +
        'onerror="this.replaceWith(document.createTextNode(\'' + esc(initialOf(name)) + '\'))"></span>';
    }
    return '<span class="' + cls + '" style="background:' + avBg(name) + '">' + esc(initialOf(name)) + '</span>';
  }

  // ==== Message model ====
  // m = { id, speakerId, name, isUser, lines:[], ts, replyTo, replyMeta,
  //       reactions:[{emoji,count,actors:[]}], images:[], kind, clientId }
  function frameToMsg(speakerId, name, isUser, text, ts, opts) {
    opts = opts || {};
    var id = opts.id != null ? opts.id : ('m' + (++msgCounter));
    return {
      id: id,
      speakerId: speakerId || '',
      name: name || speakerId || '',
      isUser: !!isUser,
      lines: text != null ? [String(text)] : [],
      ts: ts != null ? ts : Date.now(),
      replyTo: opts.replyTo != null ? opts.replyTo : null,
      threadRoot: opts.threadRoot != null ? opts.threadRoot : null,
      // Server-resolved parent context {id, author, author_id, is_user, preview}
      // — used to render a reply quote even when the parent isn't in msgIndex.
      replyMeta: opts.replyMeta || null,
      reactions: opts.reactions || [],
      images: opts.images || [],
      kind: opts.kind || 'msg',
      clientId: opts.clientId || null
    };
  }
  // Stable client-side id for an optimistic owner bubble (echo-reconcile key).
  function newClientId() {
    return 'c' + Date.now() + '-' + Math.floor(Math.random() * 1e6);
  }

  // ==== Row builders ====
  // Renders the reply quote above a bubble. Resolution order: the live msgIndex
  // (parent rendered this session) → the server-resolved replyMeta (parent
  // outside the window, from /chat/history) → the reply-cue captured object.
  function quoteHtml(m) {
    var rt = m.replyTo;
    if (rt == null) return '';
    var src = msgIndex[rt] || metaToSrc(m.replyMeta, rt) || replyToObj(rt);
    if (!src) {
      // We know there IS a parent (pointer present) but can't resolve it — still
      // render a minimal "replying" quote so the affordance is honest.
      return '<button type="button" class="quote" data-jump="' + escAttr(String(rt)) + '">' +
        '<span class="qn">Reply</span><span class="qt"></span></button>';
    }
    var qa = src.isUser
      ? '<span class="qa" style="background:' + avBg(OWNER_NAME) + '">' + esc(initialOf(OWNER_NAME)) + '</span>'
      : '<span class="qa" style="background:' + avBg(src.speakerId || src.name) + '">' + esc(initialOf(src.name)) + '</span>';
    var preview = (src.lines && src.lines.join(' ')) || '';
    return '<button type="button" class="quote" data-jump="' + escAttr(String(rt)) + '">' +
      qa + '<span class="qn">' + esc(src.name) + '</span>' +
      '<span class="qt">' + esc(preview.slice(0, 80)) + '</span></button>';
  }
  function metaToSrc(meta, rt) {
    if (!meta || meta.id == null || String(meta.id) !== String(rt)) return null;
    if (!meta.author && !meta.preview) return null;  // bare {id} pointer
    return {
      name: meta.author || '',
      isUser: !!meta.is_user,
      speakerId: meta.author_id || '',
      lines: [meta.preview || '']
    };
  }
  function replyToObj(id) {
    // The reply-cue captured object (used before the target is in msgIndex).
    if (replyTo && String(replyTo.id) === String(id)) {
      return { name: replyTo.speaker, isUser: replyTo.isUser, lines: [replyTo.text], speakerId: replyTo.speakerId };
    }
    return null;
  }

  function linesHtml(m) {
    var out = m.lines.map(function (l) { return '<div class="txt">' + rich(esc(l)) + '</div>'; }).join('');
    (m.images || []).forEach(function (im) {
      if (im && im.url) {
        out += '<img class="chat-img" src="' + escAttr(im.url) + '" alt="' + escAttr(im.caption || 'image') + '">';
        if (im.caption) out += '<div class="txt">' + rich(esc(im.caption)) + '</div>';
      }
    });
    return out;
  }

  // The thread affordance opens the REAL thread (fetch_thread). It shows for a
  // root that HAS replies (this row is itself a thread_root referenced by some
  // reply) — we render it lazily and refresh it as replies arrive / on cold-load.
  function threadAffordanceHtml(m) {
    // Persisted/optimistic ids only (temp 'm…' client ids have no server thread).
    var rootId = m.id;
    if (!isServerId(rootId)) return '';
    if (!hasReplies(rootId)) return '';
    return '<button type="button" class="thread-open" data-thread="' + escAttr(String(rootId)) + '">' +
      '<i class="ti ti-messages" aria-hidden="true"></i>View thread</button>';
  }

  // Reaction pills. ``reactions`` is [{emoji, count, actors:[ids]}]. A pill is
  // .mine when the owner is among the actors (drives toggle + accent styling).
  function reactrowHtml(m) {
    var rs = m.reactions || [];
    if (!rs.length) return '';
    var inner = rs.map(function (r) { return reactPillHtml(r); }).join('');
    return '<div class="reactrow">' + inner + '</div>';
  }
  function reactPillHtml(r) {
    var mine = OWNER_ID && (r.actors || []).indexOf(OWNER_ID) !== -1;
    return '<button type="button" class="react' + (mine ? ' mine' : '') + '"' +
      ' data-emoji="' + escAttr(r.emoji) + '" aria-pressed="' + (mine ? 'true' : 'false') + '">' +
      '<span class="e">' + esc(r.emoji) + '</span>' +
      '<span class="n">' + esc(String(r.count)) + '</span></button>';
  }
  // A row is a thread root with replies if any rendered message points at it.
  function hasReplies(rootId) {
    var key = String(rootId);
    for (var k in msgIndex) {
      if (!msgIndex.hasOwnProperty(k)) continue;
      var mm = msgIndex[k];
      if (mm && mm.replyTo != null && String(mm.replyTo) === key) return true;
    }
    return false;
  }
  function isServerId(id) {
    // Server ids are numeric; optimistic client ids are 'm…' / 'c…'.
    return id != null && /^[0-9]+$/.test(String(id));
  }

  function actsPopHtml(m) {
    var canReact = isServerId(m.id);
    return '<div class="acts-pop">' +
      (canReact
        ? '<b class="react-btn" data-react="' + escAttr(String(m.id)) + '" tabindex="0" role="button" aria-label="React">' +
            '<i class="ti ti-heart" aria-hidden="true"></i></b><span class="sep"></span>'
        : '') +
      '<b class="reply-btn" data-reply="' + escAttr(String(m.id)) + '" tabindex="0" role="button" aria-label="Reply">' +
        '<i class="ti ti-arrow-back-up" aria-hidden="true"></i></b>' +
      '<span class="sep"></span>' +
      '<b class="thread-btn" data-thread="' + escAttr(String(m.id)) + '" tabindex="0" role="button" aria-label="Thread">' +
        '<i class="ti ti-messages" aria-hidden="true"></i></b>' +
      '</div>';
  }

  // Build a row element for message m as lead or cont.
  function buildRow(m, lead) {
    var el = document.createElement('div');
    if (m.kind === 'sys' || m.kind === 'err') {
      el.className = 'msg in ' + (m.kind === 'err' ? 'err' : 'sys');
      el.innerHTML = '<div class="body">' + linesHtml(m) + '</div>';
      el.dataset.mid = m.id;
      return el;
    }
    el.className = 'msg ' + (lead ? 'lead' : 'cont');
    el.dataset.mid = m.id;
    el.dataset.speaker = m.speakerId;

    var gut = '<div class="gut">' +
      (lead ? avHtml(m.speakerId, m.name, m.isUser) : '<span class="hovertime">' + esc(clockOf(m.ts)) + '</span>') +
      '</div>';

    var tag = tagFor(m.isUser, m.speakerId);
    var head = lead
      ? '<div class="line1"><span class="who">' + esc(m.name) + '</span>' +
          (tag ? '<span class="tag ' + tag.cls + '">' + tag.label + '</span>' : '') +
          '<span class="stamp">' + esc(clockOf(m.ts)) + '</span></div>'
      : '';

    var body = '<div class="body">' +
      quoteHtml(m) + head + linesHtml(m) +
      reactrowHtml(m) +
      threadAffordanceHtml(m) +
      '</div>';

    el.innerHTML = gut + body + actsPopHtml(m);
    return el;
  }

  // ==== Append (grouping) ====
  function maybeDayDivider(container, ms) {
    var key = dateKeyOf(ms);
    if (lastRow && lastRow.dateKey === key) return false;
    var div = document.createElement('div');
    div.className = 'daydiv';
    div.innerHTML = '<span class="ln"></span><span class="lb">' + esc(dayLabelOf(ms)) + '</span><span class="ln"></span>';
    container.appendChild(div);
    return true;
  }

  function appendMessage(m, animate) {
    msgIndex[m.id] = m;
    if (m.clientId) pendingByClientId[m.clientId] = m;

    // Thread affordance: a reply means its parent is now a thread root with
    // replies — refresh the parent row's "스레드 보기" affordance if on screen.
    if (m.replyTo != null) {
      refreshThreadAffordance(String(m.replyTo));
      // If that thread panel is open, refresh it from the server.
      if (openThreadRootId != null && hasReplies(openThreadRootId)) {
        var orootM = msgIndex[m.replyTo];
        var openRoot = orootM ? rootIdOf(orootM) : null;
        if (openRoot != null && String(openRoot) === String(openThreadRootId)) {
          fetchThread(openThreadRootId);
        }
      }
    }

    var dayChanged = maybeDayDivider($stream, m.ts);

    // Grouping: continuation only when same speaker, within window, same day,
    // and this message is NOT a reply (replies start a fresh lead so the elbow
    // reads).
    var isCont = !!lastRow &&
      m.kind === 'msg' &&
      lastRow.kind === 'msg' &&
      lastRow.speakerId === m.speakerId &&
      lastRow.isUser === m.isUser &&
      (m.ts - lastRow.ts) <= GROUP_WINDOW &&
      !dayChanged &&
      m.replyTo == null;

    var el = buildRow(m, !isCont);
    $stream.appendChild(el);
    stick();
    if (animate !== false) appear(el); else el.classList.add('in');

    lastRow = { speakerId: m.speakerId, isUser: m.isUser, ts: m.ts, dateKey: dateKeyOf(m.ts), kind: m.kind };
    return el;
  }

  // The thread root id for a message: its server thread_root if it is a reply,
  // else the message's own id (a root with no parent). Falls back to the id.
  function rootIdOf(m) {
    if (!m) return null;
    if (m.threadRoot != null) return m.threadRoot;
    if (m.replyTo != null) return m.replyTo;  // 1-level fallback
    return m.id;
  }
  // Refresh the thread affordance on the ROOT row of whatever ``parentId`` (the
  // reply's target) belongs to. The root is the parent's thread_root if the
  // parent is itself a reply, else the parent id.
  function refreshThreadAffordance(parentId) {
    var parent = msgIndex[parentId];
    var rootId = parent ? rootIdOf(parent) : parentId;
    var rootEl = $stream.querySelector('.msg[data-mid="' + cssEsc(rootId) + '"]');
    if (!rootEl) return;
    var body = rootEl.querySelector('.body');
    if (!body) return;
    var existing = body.querySelector('.thread-open');
    if (existing) existing.remove();
    if (isServerId(rootId) && hasReplies(rootId)) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'thread-open';
      btn.dataset.thread = rootId;
      btn.innerHTML = '<i class="ti ti-messages" aria-hidden="true"></i>View thread';
      body.appendChild(btn);
    }
  }
  function cssEsc(s) {
    if (window.CSS && CSS.escape) return CSS.escape(String(s));
    return String(s).replace(/["\\\]]/g, '\\$&');
  }

  function clearStream() {
    $stream.innerHTML = '';
    lastRow = null;
    msgIndex = {};
    typingRows = {};
    pendingByClientId = {};
  }

  // ==== Typing (typefoot + in-stream landing spot) ====
  function showTypeFoot(on, who) {
    if (!$typefoot) return;
    if (on) {
      if ($typefootWho) $typefootWho.textContent = who || 'Someone';
      $typefoot.classList.add('show');
      $typefoot.setAttribute('aria-hidden', 'false');
    } else {
      $typefoot.classList.remove('show');
      $typefoot.setAttribute('aria-hidden', 'true');
    }
  }
  function showTyping(on, who, speakerId) {
    speakerId = speakerId || who || '__t';
    if (on) {
      showTypeFoot(true, who);
      if (typingRows[speakerId]) return;
      var ty = document.createElement('div');
      ty.className = 'typing';
      ty.dataset.speaker = speakerId;
      ty.innerHTML = '<div class="gut">' + avHtml(speakerId, who, false, 'av') + '</div>' +
        '<div class="bubble-dots"><i></i><i></i><i></i></div>';
      $stream.appendChild(ty);
      typingRows[speakerId] = ty;
      stick();
      requestAnimationFrame(function () { ty.classList.add('show'); stick(); });
    } else {
      showTypeFoot(false);
      var row = typingRows[speakerId];
      if (row) { row.remove(); delete typingRows[speakerId]; }
      // Clear any stray typing rows too.
      Object.keys(typingRows).forEach(function (k) {
        if (typingRows[k]) { typingRows[k].remove(); delete typingRows[k]; }
      });
    }
  }
  function clearTyping(speakerId) {
    // When a real text frame lands, resolve typing at the landing spot.
    if (speakerId && typingRows[speakerId]) {
      typingRows[speakerId].remove();
      delete typingRows[speakerId];
    }
    if (Object.keys(typingRows).length === 0) showTypeFoot(false);
  }

  function setStatus(state, label) {
    if (!$status) return;
    $status.setAttribute('data-state', state);
    $status.textContent = label;
  }
  function setChannelLabel(text) {
    if ($channelLabel) $channelLabel.textContent = text;
  }

  // ==== Frame handling (data flow preserved) ====
  function handleFrame(frame) {
    var type = frame && frame.type;
    // Only render frames for the active channel (the socket may briefly carry
    // frames during a switch). KEEP this guard.
    if (frame && frame.channel && frame.channel !== CHANNEL) return;
    switch (type) {
      case 'text': {
        var sid = frame.agent_id || '';
        var name = frame.speaker || frame.agent_id || '';
        // Reconcile an optimistic owner bubble: a broadcast carrying our own
        // client_msg_id swaps the temp id → real id instead of duplicating.
        if (frame.client_msg_id && pendingByClientId[frame.client_msg_id]) {
          reconcileOptimistic(frame.client_msg_id, frame.id);
          break;
        }
        clearTyping(sid);
        var m = frameToMsg(sid, name, false, frame.text || '', Date.now(), {
          id: frame.id != null ? frame.id : undefined,
          replyTo: frame.reply_to != null ? frame.reply_to : null
        });
        appendMessage(m);
        break;
      }
      case 'typing':
        showTyping(!!frame.on, frame.speaker || frame.agent_id || '', frame.agent_id || frame.speaker);
        break;
      case 'image': {
        var isid = frame.agent_id || '';
        var iname = frame.speaker || frame.agent_id || '';
        clearTyping(isid);
        var im = frameToMsg(isid, iname, false, null, Date.now(), {
          id: frame.id != null ? frame.id : undefined,
          images: [{ url: frame.url || '', caption: frame.caption || '' }]
        });
        appendMessage(im);
        break;
      }
      case 'reaction':
      case 'reaction_removed':
        applyReactionFrame(frame, type === 'reaction_removed');
        break;
      case 'thread':
        renderThreadFromServer(frame.root, frame.messages || []);
        break;
      case 'interrupted':
        showTyping(false);
        appendMessage(frameToMsg('', '', false, (frame.speaker || 'Someone') + "'s reply was interrupted.", Date.now(), { kind: 'sys' }));
        break;
      case 'error':
        showTyping(false);
        // Prefer the human-friendly `message` (e.g. demo_readonly) over the code.
        appendMessage(frameToMsg('', '', false, frame.message || frame.error || 'Something went wrong.', Date.now(), { kind: 'err' }));
        break;
      case 'pong':
        break;
      default:
        break;
    }
  }

  // Swap an optimistic owner bubble's temp id for the server id once the echo
  // lands (reconcile, not duplicate). Re-stamps the row + msgIndex + any pending
  // reaction targets.
  function reconcileOptimistic(clientId, realId) {
    var m = pendingByClientId[clientId];
    delete pendingByClientId[clientId];
    if (!m) return;
    if (realId == null) return;
    var oldId = m.id;
    var el = $stream.querySelector('.msg[data-mid="' + cssEsc(oldId) + '"]');
    delete msgIndex[oldId];
    m.id = realId;
    m.clientId = null;
    msgIndex[realId] = m;
    if (el) {
      el.dataset.mid = realId;
      // Now that the row has a real id, it can be reacted to — rebuild acts-pop.
      var pop = el.querySelector('.acts-pop');
      if (pop) { pop.outerHTML = actsPopHtml(m); }
    }
  }

  // Apply a reaction add/remove broadcast to the target row's pill set. The
  // server's authoritative ``count`` reconciles any optimistic local pill.
  function applyReactionFrame(frame, removed) {
    var id = frame.id;
    var m = msgIndex[id];
    var emoji = frame.emoji;
    var actor = frame.actor_id;
    var count = frame.count != null ? frame.count : 0;
    // Bind OWNER_ID from our own reaction echo: if we just sent this exact
    // reaction, the broadcast's actor IS the owner id the server records. This
    // lets the "mine" pill state resolve even before any history is loaded, and
    // migrates any optimistic '__me' placeholder actor to the real id.
    if (pendingReaction && pendingReaction.emoji === emoji &&
        String(pendingReaction.id) === String(id)) {
      if (OWNER_ID == null) OWNER_ID = actor;
      pendingReaction = null;
      if (m) migrateOptimisticActor(m, emoji, actor);
    }
    if (m) {
      m.reactions = mergeReaction(m.reactions || [], emoji, actor, count, removed);
    }
    renderReactrow(id, m ? m.reactions : reconstructReactions(id, emoji, actor, count, removed));
  }
  // Replace the '__me' placeholder actor with the real owner id on a pill (so the
  // count isn't double-counted when the authoritative actor merges in).
  function migrateOptimisticActor(m, emoji, realActor) {
    (m.reactions || []).forEach(function (r) {
      if (r.emoji !== emoji || !r.actors) return;
      var i = r.actors.indexOf('__me');
      if (i !== -1) r.actors[i] = realActor;
    });
  }
  // Merge a single emoji's authoritative state into a reactions array.
  function mergeReaction(reactions, emoji, actor, count, removed) {
    var out = reactions.slice();
    var idx = -1;
    for (var i = 0; i < out.length; i++) { if (out[i].emoji === emoji) { idx = i; break; } }
    if (count <= 0) { if (idx !== -1) out.splice(idx, 1); return out; }
    var actors;
    if (idx !== -1) {
      actors = (out[idx].actors || []).slice();
    } else {
      actors = [];
    }
    var ai = actors.indexOf(actor);
    if (removed) { if (ai !== -1) actors.splice(ai, 1); }
    else { if (ai === -1) actors.push(actor); }
    var pill = { emoji: emoji, count: count, actors: actors };
    if (idx !== -1) out[idx] = pill; else out.push(pill);
    return out;
  }
  function reconstructReactions(id, emoji, actor, count, removed) {
    return mergeReaction([], emoji, actor, count, removed);
  }
  // Re-render the .reactrow for a message row from its reactions array.
  function renderReactrow(id, reactions) {
    var el = $stream.querySelector('.msg[data-mid="' + cssEsc(id) + '"]');
    if (!el) return;
    var body = el.querySelector('.body');
    if (!body) return;
    var existing = body.querySelector('.reactrow');
    var html = (reactions && reactions.length)
      ? reactions.map(function (r) { return reactPillHtml(r); }).join('') : '';
    if (!html) { if (existing) existing.remove(); return; }
    if (existing) { existing.innerHTML = html; }
    else {
      var row = document.createElement('div');
      row.className = 'reactrow';
      row.innerHTML = html;
      // Insert before the thread affordance if present, else append.
      var to = body.querySelector('.thread-open');
      if (to) body.insertBefore(row, to); else body.appendChild(row);
    }
  }

  // ==== History cold-load ====
  function loadHistory() {
    var url = apiBase() + '/history?channel=' + encodeURIComponent(CHANNEL) + '&limit=50';
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { messages: [] }; })
      .then(function (data) {
        clearStream();
        pinned = true;
        var msgs = (data && data.messages) || [];
        msgs.forEach(function (row) {
          // Capture the owner's speaker id once so reaction "mine" state matches.
          if (row.is_user && row.speaker_id && OWNER_ID == null) OWNER_ID = row.speaker_id;
          var rt = (row.reply_to && row.reply_to.id != null) ? row.reply_to.id : null;
          var m = frameToMsg(
            row.speaker_id, row.display_name || row.speaker_id || '',
            !!row.is_user, row.text || '', parseTs(row.timestamp),
            {
              id: row.id != null ? row.id : undefined,
              images: row.images || [],
              reactions: row.reactions || [],
              replyTo: rt,
              replyMeta: row.reply_to || null,
              threadRoot: row.thread_root != null ? row.thread_root : null
            }
          );
          appendMessage(m, false);  // no enter animation on cold-load
        });
        // A second pass: now that all rows are indexed, refresh thread
        // affordances on roots whose replies were loaded after them.
        msgs.forEach(function (row) {
          if (row.reply_to && row.reply_to.id != null) refreshThreadAffordance(String(row.reply_to.id));
        });
        updateChannelPreviewFromHistory(msgs);
        pinned = true;
        stick();
      })
      .catch(function () { /* leave whatever is shown */ });
  }

  // Derive the active channel's last-message preview/time from its history.
  function updateChannelPreviewFromHistory(msgs) {
    if (!msgs || !msgs.length) return;
    var last = msgs[msgs.length - 1];
    var c = channels.filter(function (x) { return x.channel === CHANNEL; })[0];
    if (!c) return;
    c._preview = (last.is_user ? (OWNER_NAME + ': ') : ((last.display_name || '') + ': ')) + (last.text || '');
    c._ts = parseTs(last.timestamp);
    renderChannels();
  }

  // ==== Channel list ====
  function groupLabel(text, count) {
    var li = document.createElement('li');
    li.className = 'grp-l' + (count === 0 || $channelList.children.length === 0 ? ' first' : '');
    li.innerHTML = '<span>' + esc(text) + '</span><span class="count">' + count + '</span>';
    return li;
  }

  function rowFor(c) {
    var li = document.createElement('li');
    var on = c.channel === CHANNEL;
    var u = unread[c.channel] || 0;
    li.className = 'row' + (on ? ' on' : '') + (u > 0 ? ' unread' : '');
    li.setAttribute('role', 'button');
    li.tabIndex = 0;
    li.dataset.channel = c.channel;
    li.dataset.agent = c.agent_id || '';

    var html = '<span class="tick"></span>';
    if (c.kind === 'dm' && c.agent_id) {
      html += '<span class="ava" style="background:' + avBg(c.agent_id) + '">' +
        '<img src="' + escAttr(avatarUrl(c.agent_id)) + '" alt="" ' +
        'onerror="this.replaceWith(document.createTextNode(\'' + esc(initialOf(c.name)) + '\'))">' +
        '<span class="pres online"></span></span>';
    } else {
      html += '<i class="ti ti-hash hash" aria-hidden="true"></i>';
    }
    var preview = c._preview ? '<span class="p">' + esc(c._preview) + '</span>' : '';
    html += '<span class="meta"><span class="t">' + esc(c.name || c.channel) + '</span>' + preview + '</span>';

    // Right-edge slot: exactly one of pill > time > lock.
    if (u > 0) {
      html += '<span class="pill' + (u >= 10 ? ' calm' : '') + '">' + (u >= 10 ? '9+' : u) + '</span>';
    } else if (c._ts) {
      html += '<span class="when">' + esc(relTime(c._ts)) + '</span>';
    }
    li.innerHTML = html;

    li.addEventListener('click', function () { selectChannel(c); });
    li.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectChannel(c); }
    });
    return li;
  }

  function renderChannels() {
    if (!$channelList) return;
    var q = ($search && $search.value || '').trim().toLowerCase();
    var match = function (c) {
      if (!q) return true;
      return (c.name || c.channel || '').toLowerCase().indexOf(q) !== -1;
    };
    var dms = channels.filter(function (c) { return c.kind === 'dm' && match(c); });
    var grps = channels.filter(function (c) { return c.kind === 'group' && match(c); });

    $channelList.innerHTML = '';
    if (dms.length) {
      $channelList.appendChild(groupLabel('Direct', dms.length));
      dms.forEach(function (c) { $channelList.appendChild(rowFor(c)); });
    }
    if (grps.length) {
      $channelList.appendChild(groupLabel('Channels', grps.length));
      grps.forEach(function (c) { $channelList.appendChild(rowFor(c)); });
    }

    // Sidebar sub-header: derive friend/online counts from /channels (no
    // presence API → online == DM count as a neutral default).
    if ($sideSub) {
      var n = dms.length;
      var noun = WS_BASE ? 'members' : 'friends';
      $sideSub.textContent = n + ' ' + noun + ' · ' + n + ' online';
    }
  }

  function loadChannels() {
    return fetch(apiBase() + '/channels', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { channels: [] }; })
      .then(function (data) {
        channels = (data && data.channels) || [];
        // Seed each row's last-message preview/time from the server so recent
        // activity is visible WITHOUT opening every channel first.
        channels.forEach(function (c) {
          var last = c.last;
          if (last && last.text) {
            c._preview = (last.is_user ? (OWNER_NAME + ': ')
                          : ((last.display_name || '') + ': ')) + last.text;
            c._ts = parseTs(last.timestamp);
          }
        });
        renderChannels();
        syncHead();
      })
      .catch(function () { /* no sidebar data */ });
  }

  function syncHead() {
    var c = channels.filter(function (x) { return x.channel === CHANNEL; })[0];
    if (c) {
      setChannelLabel(c.name || c.channel);
      if ($headIcon) {
        $headIcon.className = (c.kind === 'dm' ? 'ti ti-at hash' : 'ti ti-hash hash');
      }
      if ($input) {
        var ph = 'Message ' + (c.name || c.channel) + '…';
        $input.setAttribute('data-ph', ph);
        $input.setAttribute('aria-label', 'Message ' + (c.name || c.channel));
      }
    } else {
      setChannelLabel('# ' + CHANNEL);
    }
  }

  function selectChannel(c) {
    if (!c || c.channel === CHANNEL) { closeSidebarMobile(); return; }
    CHANNEL = c.channel;
    AGENT = c.agent_id || AGENT;
    unread[CHANNEL] = 0;          // clear unread for the opened channel
    clearReplyCue();
    closeThreadPanel();
    syncHead();
    renderChannels();
    closeSidebarMobile();
    // Cold-load history, then (re)connect the socket. KEEP this ordering.
    loadHistory().then(function () { reconnect(); });
  }

  // ==== Sidebar (mobile drawer) ====
  function openSidebarMobile() {
    if ($sidebar) $sidebar.classList.add('is-open');
    if ($scrim) { $scrim.hidden = false; requestAnimationFrame(function () { $scrim.classList.add('show'); }); }
    if ($sidebarToggle) $sidebarToggle.setAttribute('aria-expanded', 'true');
  }
  function closeSidebarMobile() {
    if ($sidebar) $sidebar.classList.remove('is-open');
    if ($scrim) {
      $scrim.classList.remove('show');
      setTimeout(function () { if (!$scrim.classList.contains('show')) $scrim.hidden = true; }, 220);
    }
    if ($sidebarToggle) $sidebarToggle.setAttribute('aria-expanded', 'false');
  }
  if ($sidebarToggle && $sidebar) {
    $sidebarToggle.addEventListener('click', function () {
      if ($sidebar.classList.contains('is-open')) closeSidebarMobile();
      else openSidebarMobile();
    });
  }
  if ($scrim) $scrim.addEventListener('click', closeSidebarMobile);
  if ($sideRefresh) $sideRefresh.addEventListener('click', function () { loadChannels(); });
  if ($search) $search.addEventListener('input', renderChannels);

  // ==== Connection (reconnect-with-backoff) ====
  // A backgrounded mobile tab drops its socket; recover automatically with
  // exponential backoff (capped) so the chat survives sleep/resume without a
  // manual reload. ``intentionalClose`` suppresses reconnect on a channel switch
  // (reconnect() tears down then connects fresh).
  var reconnectAttempts = 0;
  var reconnectTimer = null;
  var intentionalClose = false;
  var RECONNECT_MAX = 15000;  // 15s cap

  function wsUrl() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + location.host + apiBase() + '/ws';
  }
  function scheduleReconnect() {
    if (intentionalClose) return;
    if (reconnectTimer) return;
    var delay = Math.min(RECONNECT_MAX, 500 * Math.pow(2, reconnectAttempts));
    reconnectAttempts++;
    setStatus('connecting', 'Reconnecting…');
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connect();
    }, delay);
  }
  function connect() {
    intentionalClose = false;
    setStatus('connecting', 'Connecting…');
    try {
      ws = new WebSocket(wsUrl());
    } catch (e) {
      setStatus('closed', 'Connection failed');
      scheduleReconnect();
      return;
    }
    ws.onopen = function () {
      reconnectAttempts = 0;
      setStatus('open', 'Connected');
      syncSendDisabled();
      try { ws.send(JSON.stringify({ type: 'ping', channel: CHANNEL, agent: AGENT })); } catch (e2) {}
    };
    ws.onmessage = function (ev) {
      var frame;
      try { frame = JSON.parse(ev.data); } catch (e) { return; }
      handleFrame(frame);
    };
    ws.onclose = function () {
      setStatus('closed', 'Disconnected');
      syncSendDisabled();
      showTyping(false);
      scheduleReconnect();
    };
    ws.onerror = function () {
      setStatus('closed', 'Connection error');
      // onclose fires after onerror → reconnect is scheduled there.
    };
  }
  function reconnect() {
    intentionalClose = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    reconnectAttempts = 0;
    if (ws) {
      try { ws.onclose = null; ws.close(); } catch (e) {}
      ws = null;
    }
    connect();
  }
  // Recover proactively when a backgrounded tab returns to the foreground.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' &&
        (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING)) {
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      reconnectAttempts = 0;
      connect();
    }
  });

  function sendText(text, replyToId, clientId) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    var frame = { type: 'text', channel: CHANNEL, agent: AGENT, text: text };
    // reply_to is now PERSISTED by the backend (pointer backfilled onto the
    // human turn) and round-trips through /chat/history.
    if (replyToId != null) frame.reply_to = replyToId;
    if (clientId) frame.client_msg_id = clientId;
    ws.send(JSON.stringify(frame));
    return true;
  }
  // Reaction send: optimistic local toggle, reconciled by the broadcast count.
  function sendReaction(targetId, emoji, on) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({
      type: on ? 'add_reaction' : 'remove_reaction',
      channel: CHANNEL, id: Number(targetId), emoji: emoji
    }));
    return true;
  }
  function fetchThread(rootId) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: 'fetch_thread', channel: CHANNEL, root: Number(rootId) }));
    return true;
  }
  // Toggle the default emoji on a message: optimistic pill, send the frame, the
  // server's broadcast reconciles the authoritative count.
  function toggleReaction(targetId, emoji) {
    emoji = emoji || DEFAULT_EMOJI;
    var m = msgIndex[targetId];
    if (!m) return;
    var existing = null;
    (m.reactions || []).forEach(function (r) { if (r.emoji === emoji) existing = r; });
    var mineNow = !!(existing && OWNER_ID && (existing.actors || []).indexOf(OWNER_ID) !== -1);
    var on = !mineNow;  // toggle
    // Optimistic local update (count ±1, actor in/out) — reconciled on broadcast.
    var optimisticCount = (existing ? existing.count : 0) + (on ? 1 : -1);
    if (optimisticCount < 0) optimisticCount = 0;
    m.reactions = mergeReaction(m.reactions || [], emoji, OWNER_ID || '__me', optimisticCount, !on);
    renderReactrow(targetId, m.reactions);
    pendingReaction = { id: targetId, emoji: emoji };
    sendReaction(targetId, emoji, on);
  }

  // ==== Composer (2-tier contenteditable) ====
  function fieldText() {
    // Convert <div>/<br> line breaks to \n; contenteditable text.
    return ($input.innerText != null ? $input.innerText : $input.textContent || '')
      .replace(/ /g, ' ');
  }
  function clearField() { $input.innerHTML = ''; syncComposer(); }

  function syncSendDisabled() {
    if (READONLY) { if ($send) $send.disabled = true; return; }
    var open = ws && ws.readyState === WebSocket.OPEN;
    var has = fieldText().trim().length > 0;
    if ($send) $send.disabled = !(open && has);
  }

  // Look-only mockup: lock the composer (no edits/sends) + reveal the banner.
  // Idempotent — safe to call once on init.
  function applyReadonly() {
    if (!READONLY) return;
    if ($input) {
      $input.setAttribute('contenteditable', 'false');
      $input.setAttribute('aria-disabled', 'true');
    }
    if ($send) $send.disabled = true;
    if ($cbox) $cbox.classList.add('readonly');
    // mark the composer wrapper so CSS can dim it
    var composer = $cbox ? $cbox.closest('.composer') : null;
    if (composer) composer.classList.add('readonly');
    if ($readonlyBanner) $readonlyBanner.hidden = false;
  }
  function syncComposer() {
    var raw = fieldText();
    var len = raw.length;
    // Enforce the 2000 cap (refuse input past the cap).
    if (len > MAX_LEN) {
      // Trim back to the cap.
      $input.textContent = raw.slice(0, MAX_LEN);
      placeCaretEnd($input);
      raw = fieldText();
      len = raw.length;
    }
    $cbox.classList.toggle('has', raw.trim().length > 0);
    if (len >= CNT_REVEAL) {
      $cnt.hidden = false;
      $cnt.textContent = len + ' / ' + MAX_LEN;
      $cnt.classList.toggle('over', len >= CNT_WARN);
    } else {
      $cnt.hidden = true;
    }
    syncSendDisabled();
  }
  function placeCaretEnd(el) {
    try {
      var r = document.createRange();
      r.selectNodeContents(el);
      r.collapse(false);
      var s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
    } catch (e) {}
  }

  if ($input) {
    $input.addEventListener('focus', function () { $cbox.classList.add('foc'); });
    $input.addEventListener('blur', function () { $cbox.classList.remove('foc'); });
    $input.addEventListener('input', syncComposer);
    $input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitComposer(); }
      else if (e.key === 'Escape' && replyTo) { e.preventDefault(); clearReplyCue(); }
    });
    // Paste as plain text to keep the field clean / honor the cap.
    $input.addEventListener('paste', function (e) {
      e.preventDefault();
      var t = (e.clipboardData || window.clipboardData).getData('text');
      document.execCommand('insertText', false, t);
    });
  }
  if ($send) $send.addEventListener('click', submitComposer);

  // Lock the composer immediately at load for read-only (demo) communities.
  applyReadonly();

  function submitComposer() {
    if (READONLY) return;  // look-only mockup — never send
    var text = fieldText().trim();
    if (!text) return;
    var rt = replyTo ? replyTo.id : null;
    // reply_to must be a server id to persist; a temp id can't be a parent.
    if (rt != null && !isServerId(rt)) rt = null;
    var clientId = newClientId();
    if (!sendText(text, rt, clientId)) return;  // gated on ws OPEN
    // Optimistic local echo of the owner's message — left-aligned grouped row.
    // Reconciled to the server id when its broadcast echo (carrying client_msg_id)
    // lands. ``replyMeta`` is seeded from the captured reply-cue so the optimistic
    // quote renders before the echo.
    var ownerId = OWNER_ID || '__owner';
    var meta = (replyTo && rt != null) ? {
      id: rt, author: replyTo.speaker, author_id: replyTo.speakerId,
      is_user: replyTo.isUser, preview: replyTo.text
    } : null;
    var m = frameToMsg(ownerId, OWNER_NAME, true, text, Date.now(), {
      replyTo: rt, replyMeta: meta, clientId: clientId
    });
    appendMessage(m);
    clearField();
    clearReplyCue();
    $input.focus();
  }

  // ==== Reply-cue + threads ====
  function setReplyTo(id) {
    var src = msgIndex[id];
    if (!src) return;
    replyTo = {
      id: id,
      speaker: src.name,
      speakerId: src.speakerId,
      isUser: src.isUser,
      text: (src.lines && src.lines.join(' ')) || ''
    };
    $replyCue.hidden = false;
    $replyCueText.innerHTML = 'Replying to <b>' + esc(src.name) + '</b> — ' + esc(replyTo.text.slice(0, 40));
    $input.focus();
  }
  function clearReplyCue() {
    replyTo = null;
    if ($replyCue) $replyCue.hidden = true;
  }
  if ($replyCueClear) $replyCueClear.addEventListener('click', clearReplyCue);

  // Delegated clicks for in-stream actions (react / reply / thread / quote jump).
  function midOfEvent(e) {
    var row = e.target.closest && e.target.closest('.msg[data-mid]');
    return row ? row.dataset.mid : null;
  }
  $stream.addEventListener('click', function (e) {
    // A reaction pill toggles its own emoji on this row.
    var pill = e.target.closest && e.target.closest('.react[data-emoji]');
    if (pill) {
      var mid = midOfEvent(e);
      if (mid && isServerId(mid)) toggleReaction(mid, pill.getAttribute('data-emoji'));
      return;
    }
    var reactBtn = e.target.closest && e.target.closest('[data-react]');
    if (reactBtn) { toggleReaction(reactBtn.getAttribute('data-react'), DEFAULT_EMOJI); return; }
    var replyBtn = e.target.closest && e.target.closest('[data-reply]');
    if (replyBtn) { setReplyTo(replyBtn.getAttribute('data-reply')); return; }
    var threadBtn = e.target.closest && e.target.closest('[data-thread]');
    if (threadBtn) { openThreadPanel(threadBtn.getAttribute('data-thread')); return; }
    var jump = e.target.closest && e.target.closest('[data-jump]');
    if (jump) { jumpToMessage(jump.getAttribute('data-jump')); return; }
  });
  $stream.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var b = e.target.closest && e.target.closest('[data-react],[data-reply],[data-thread],.react[data-emoji]');
    if (!b) return;
    e.preventDefault();
    if (b.classList.contains('react')) {
      var mid = midOfEvent(e);
      if (mid && isServerId(mid)) toggleReaction(mid, b.getAttribute('data-emoji'));
    } else if (b.hasAttribute('data-react')) {
      toggleReaction(b.getAttribute('data-react'), DEFAULT_EMOJI);
    } else if (b.hasAttribute('data-reply')) {
      setReplyTo(b.getAttribute('data-reply'));
    } else {
      openThreadPanel(b.getAttribute('data-thread'));
    }
  });

  function jumpToMessage(id) {
    var el = $stream.querySelector('.msg[data-mid="' + cssEsc(id) + '"]');
    if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
  }

  // ==== Thread panel (REAL server thread via fetch_thread) ====
  // Render the thread panel from a server ``thread`` frame (root + replies). The
  // rows are server-resolved (display name + is_user + reactions), so we build a
  // lightweight message model per row and render them read-only.
  function renderThreadFromServer(rootId, rows) {
    // Only render if this is the thread the user has open (a stale frame from a
    // previous open is ignored).
    if (openThreadRootId == null || String(openThreadRootId) !== String(rootId)) return;
    var models = (rows || []).map(function (row) {
      var rt = (row.reply_to && row.reply_to.id != null) ? row.reply_to.id : null;
      return frameToMsg(
        row.speaker_id, row.display_name || row.speaker_id || '',
        !!row.is_user, row.text || '', parseTs(row.timestamp),
        {
          id: row.id != null ? row.id : undefined,
          reactions: row.reactions || [],
          replyTo: rt,
          threadRoot: row.thread_root != null ? row.thread_root : null
        }
      );
    });
    var root = models[0] || msgIndex[rootId];
    var replyCount = Math.max(0, models.length - 1);
    if ($threadSub) {
      $threadSub.textContent = (root ? (root.name + ' · ') : '') + replyCount + (replyCount === 1 ? ' reply' : ' replies');
    }
    $threadBody.innerHTML = '';
    models.forEach(function (r) { $threadBody.appendChild(threadRow(r, true)); });
    if (!models.length) {
      var empty = document.createElement('div');
      empty.className = 'msg sys in';
      empty.innerHTML = '<div class="body"><div class="txt">Thread not found.</div></div>';
      $threadBody.appendChild(empty);
    }

    // Footer = a "reply to thread" affordance that seeds the reply-cue to root.
    $threadFoot.innerHTML = '';
    if (root && isServerId(root.id)) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tp-reply';
      btn.innerHTML = '<i class="ti ti-arrow-back-up" aria-hidden="true"></i><span>Reply to ' +
        esc(root.name) + '</span>';
      btn.addEventListener('click', function () {
        // Seed the reply-cue from the (possibly panel-only) root model.
        replyTo = {
          id: root.id, speaker: root.name, speakerId: root.speakerId,
          isUser: root.isUser, text: (root.lines && root.lines.join(' ')) || ''
        };
        if ($replyCue) {
          $replyCue.hidden = false;
          $replyCueText.innerHTML = 'Replying to <b>' + esc(root.name) + '</b> — ' +
            esc(replyTo.text.slice(0, 40));
        }
        closeThreadPanel();
        $input.focus();
      });
      $threadFoot.appendChild(btn);
    }
  }
  function threadRow(m, lead) {
    var el = buildRow(m, lead);
    var pop = el.querySelector('.acts-pop');
    if (pop) pop.remove();
    var to = el.querySelector('.thread-open');
    if (to) to.remove();
    el.classList.add('in');
    return el;
  }
  function openThreadPanel(rootId) {
    // Resolve the actual thread root: if the clicked row is itself a reply, open
    // its thread_root; else it IS the root.
    var clicked = msgIndex[rootId];
    var actualRoot = clicked ? rootIdOf(clicked) : rootId;
    if (!isServerId(actualRoot)) return;
    openThreadRootId = actualRoot;
    lastFocused = document.activeElement;
    // Show a loading shell, then fetch the real thread over the socket.
    if ($threadSub) $threadSub.textContent = 'Loading…';
    $threadBody.innerHTML = '';
    $threadFoot.innerHTML = '';
    $threadPanel.hidden = false;
    $threadPanel.setAttribute('aria-modal', isNarrow() ? 'true' : 'false');
    requestAnimationFrame(function () { $threadPanel.classList.add('open'); });
    if ($threadToggle) { $threadToggle.hidden = false; $threadToggle.classList.add('on'); }
    if ($threadClose) $threadClose.focus();
    fetchThread(actualRoot);
  }
  function closeThreadPanel() {
    if (!openThreadRootId) { $threadPanel.hidden = true; return; }
    openThreadRootId = null;
    $threadPanel.classList.remove('open');
    if ($threadToggle) $threadToggle.classList.remove('on');
    setTimeout(function () { if (!openThreadRootId) $threadPanel.hidden = true; }, 220);
    if (lastFocused && lastFocused.focus) { try { lastFocused.focus(); } catch (e) {} }
  }
  function isNarrow() { return window.matchMedia && window.matchMedia('(max-width: 720px)').matches; }
  if ($threadClose) $threadClose.addEventListener('click', closeThreadPanel);
  if ($threadToggle) $threadToggle.addEventListener('click', function () {
    if (openThreadRootId) closeThreadPanel();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && openThreadRootId) { closeThreadPanel(); }
  });

  // ==== Mobile: on-screen keyboard handling (visualViewport) ====
  // 100dvh alone does NOT track the soft keyboard. When the keyboard opens,
  // visualViewport.height shrinks; lift the composer by the occluded amount via
  // --kb-inset and keep the feed pinned to bottom so the latest message + the
  // composer stay visible above the keyboard.
  (function () {
    var vv = window.visualViewport;
    if (!vv) return;
    function onViewport() {
      // Occluded height = layout viewport - (visual viewport height + its top
      // offset). On desktop / no keyboard this is ~0.
      var occluded = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      if (occluded < 2) occluded = 0;  // ignore sub-pixel noise
      if ($shell) $shell.style.setProperty('--kb-inset', occluded + 'px');
      // Keep the conversation pinned to bottom while the keyboard animates in.
      if (pinned) requestAnimationFrame(stick);
    }
    vv.addEventListener('resize', onViewport);
    vv.addEventListener('scroll', onViewport);
    // Re-pin when the input gains focus (keyboard about to open).
    if ($input) $input.addEventListener('focus', function () {
      setTimeout(function () { if (pinned) stick(); }, 250);
    });
  })();

  // ==== Boot / public API ====
  // The DOM consts + listener bindings above run ONCE at load (idempotent, bind
  // to the single #view-chat / chat.html instance). Only the data-loading boot
  // (channel list + history cold-load + WS connect) is deferred behind init() so
  // the embedded dashboard can lazy-start it on first Chat-tab entry.
  var _inited = false;
  function _boot() {
    setChannelLabel('# ' + CHANNEL);
    loadChannels().then(function () {
      // If the seeded default channel isn't a real one (e.g. an empty 'dm-mgr'
      // placeholder), fall back to the first actual channel so the chat opens on
      // a live conversation instead of a blank pane.
      if (channels.length && !channels.some(function (x) { return x.channel === CHANNEL; })) {
        var c = channels[0];
        CHANNEL = c.channel;
        AGENT = c.agent_id || AGENT;
        renderChannels();
        syncHead();
      }
      loadHistory().then(function () { connect(); });
    });
  }
  window.GlimiChat = {
    // Idempotent: first call boots (channels + history + WS); later calls no-op.
    init: function () {
      if (_inited) return;
      _inited = true;
      _boot();
    },
    // Graph→chat jump: switch to channelId on the single live WS. Reuses
    // selectChannel (history reload + WS reconnect on channel change). If not
    // yet inited, seed the target then boot straight onto it.
    selectChannelById: function (channelId, agentId) {
      if (!channelId) return;
      if (!_inited) {
        CHANNEL = channelId;
        if (agentId) AGENT = agentId;
        window.GlimiChat.init();
        return;
      }
      var resolvedAgent = agentId ||
        (channelId.indexOf('dm-') === 0 ? channelId.slice(3) : AGENT);
      // selectChannel early-returns when the target is already the active
      // channel — that's correct here (the channel is already live; the caller
      // has already shown the tab), so the jump is a safe no-op in that case.
      selectChannel({ channel: channelId, agent_id: resolvedAgent });
    },
    // Re-entry into the Chat tab: re-pin the feed to bottom (the WS is untouched).
    refit: function () { if ($feed) { pinned = true; $feed.scrollTop = $feed.scrollHeight; } }
  };

  // Standalone /chat auto-boots; embedded dashboard lazy-inits on first tab entry.
  if (!EMBEDDED) window.GlimiChat.init();
})();
