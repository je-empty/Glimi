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
// THREADS — v1 is client/session-local. The reply action sets a composer
// reply-cue and the WS text frame carries `reply_to:<msgId>`. The backend
// (routers/chat.py chat_ws) reads only type/channel/agent/text, so reply_to is
// a SAFE passthrough but is NOT persisted — /chat/history has no reply_to
// column, so threads reset on reload. BACKEND FOLLOW-UP (do not block this
// redesign): add a reply_to column + persist it on the WS text path + include
// reply_to in the /chat/history row shape so threads survive reload.
(function () {
  'use strict';

  // ==== State (injected by template, URL fallback) ====
  var params = new URLSearchParams(location.search);
  var COMMUNITY = window.__GLIMI_COMMUNITY__ || params.get('community') || '';
  var CHANNEL = window.__GLIMI_CHANNEL__ || params.get('channel') || '';
  var AGENT = window.__GLIMI_AGENT__ || params.get('agent') || 'mgr';
  var OWNER_NAME = window.__GLIMI_USER__ || '나';

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
  // Threads: rootId → [reply message objects] (client/session-local only).
  var threadsByRoot = {};
  // Reply target captured from a message's reply action.
  var replyTo = null;        // { id, speaker, text }
  // Thread panel state.
  var openThreadRootId = null;
  var lastFocused = null;
  // Session-local unread counts per channel (no backend support).
  var unread = {};
  // In-stream typing rows keyed by speakerId.
  var typingRows = {};

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
    return '/community/' + encodeURIComponent(COMMUNITY) + '/chat';
  }
  function avatarUrl(agentId) {
    return '/api/avatar?id=' + encodeURIComponent(agentId) +
      (COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : '');
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
      return new Date(ms).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    } catch (e) { return ''; }
  }
  function dayLabelOf(ms) {
    try {
      return new Date(ms).toLocaleDateString([], { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
    } catch (e) { return ''; }
  }
  function relTime(ms) {
    var diff = Date.now() - ms;
    if (diff < 60000) return '방금';
    if (diff < 3600000) return Math.floor(diff / 60000) + '분';
    if (diff < 86400000) return Math.floor(diff / 3600000) + '시간';
    if (diff < 172800000) return '어제';
    return Math.floor(diff / 86400000) + '일';
  }

  // Role tag for the active channel's type (DM) / owner.
  function activeChannelType() {
    var c = channels.filter(function (x) { return x.channel === CHANNEL; })[0];
    return c ? (c.type || '') : '';
  }
  function tagFor(isUser, speakerId) {
    if (isUser) return { cls: 'me', label: '나' };
    // For DM channels the responding agent's type drives the tag.
    if (CHANNEL.indexOf('dm-') === 0 && speakerId === AGENT) {
      if (activeChannelType() === 'mgr') return { cls: 'mgr', label: '매니저' };
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
  // m = { id, speakerId, name, isUser, lines:[], ts, replyTo, images:[], kind }
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
      replyTo: opts.replyTo || null,
      images: opts.images || [],
      kind: opts.kind || 'msg'
    };
  }

  // ==== Row builders ====
  function quoteHtml(rt) {
    if (!rt) return '';
    var src = msgIndex[rt] || replyToObj(rt);
    if (!src) return '';
    var qa = src.isUser
      ? '<span class="qa" style="background:' + avBg(OWNER_NAME) + '">' + esc(initialOf(OWNER_NAME)) + '</span>'
      : '<span class="qa" style="background:' + avBg(src.speakerId || src.name) + '">' + esc(initialOf(src.name)) + '</span>';
    var preview = (src.lines && src.lines.join(' ')) || '';
    return '<button type="button" class="quote" data-jump="' + escAttr(String(rt)) + '">' +
      qa + '<span class="qn">' + esc(src.name) + '</span>' +
      '<span class="qt">' + esc(preview.slice(0, 80)) + '</span></button>';
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

  function threadAffordanceHtml(m) {
    var n = (threadsByRoot[m.id] || []).length;
    if (!n) return '';
    return '<button type="button" class="thread-open" data-thread="' + escAttr(String(m.id)) + '">' +
      '<i class="ti ti-messages" aria-hidden="true"></i>스레드 ' + n + '개</button>';
  }

  function actsPopHtml(m) {
    return '<div class="acts-pop">' +
      '<b class="reply-btn" data-reply="' + escAttr(String(m.id)) + '" tabindex="0" role="button" aria-label="답장">' +
        '<i class="ti ti-arrow-back-up" aria-hidden="true"></i></b>' +
      '<span class="sep"></span>' +
      '<b class="thread-btn" data-thread="' + escAttr(String(m.id)) + '" tabindex="0" role="button" aria-label="스레드">' +
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
      quoteHtml(m.replyTo) + head + linesHtml(m) +
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

    // Thread membership: a reply registers under its root.
    if (m.replyTo != null) {
      var root = String(m.replyTo);
      (threadsByRoot[root] = threadsByRoot[root] || []).push(m);
      // Refresh the root row's affordance if it's already on screen.
      refreshThreadAffordance(root);
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

  function refreshThreadAffordance(rootId) {
    var rootEl = $stream.querySelector('.msg[data-mid="' + cssEsc(rootId) + '"]');
    if (!rootEl) return;
    var body = rootEl.querySelector('.body');
    if (!body) return;
    var existing = body.querySelector('.thread-open');
    var n = (threadsByRoot[rootId] || []).length;
    if (existing) existing.remove();
    if (n > 0) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'thread-open';
      btn.dataset.thread = rootId;
      btn.innerHTML = '<i class="ti ti-messages" aria-hidden="true"></i>스레드 ' + n + '개';
      body.appendChild(btn);
    }
    if (openThreadRootId === rootId) renderThreadPanel(rootId);
  }
  function cssEsc(s) {
    if (window.CSS && CSS.escape) return CSS.escape(String(s));
    return String(s).replace(/["\\\]]/g, '\\$&');
  }

  function clearStream() {
    $stream.innerHTML = '';
    lastRow = null;
    msgIndex = {};
    threadsByRoot = {};
    typingRows = {};
  }

  // ==== Typing (typefoot + in-stream landing spot) ====
  function showTypeFoot(on, who) {
    if (!$typefoot) return;
    if (on) {
      if ($typefootWho) $typefootWho.textContent = who || '상대';
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
        clearTyping(sid);
        var m = frameToMsg(sid, name, false, frame.text || '', Date.now(), {
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
          images: [{ url: frame.url || '', caption: frame.caption || '' }]
        });
        appendMessage(im);
        break;
      }
      case 'interrupted':
        showTyping(false);
        appendMessage(frameToMsg('', '', false, (frame.speaker || '상대') + '의 응답이 중단되었습니다.', Date.now(), { kind: 'sys' }));
        break;
      case 'error':
        showTyping(false);
        appendMessage(frameToMsg('', '', false, frame.error || '오류가 발생했습니다.', Date.now(), { kind: 'err' }));
        break;
      case 'pong':
        break;
      default:
        break;
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
          var m = frameToMsg(
            row.speaker_id, row.display_name || row.speaker_id || '',
            !!row.is_user, row.text || '', parseTs(row.timestamp),
            { id: row.id != null ? row.id : undefined, images: row.images || [] }
          );
          appendMessage(m, false);  // no enter animation on cold-load
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
      $channelList.appendChild(groupLabel('다이렉트', dms.length));
      dms.forEach(function (c) { $channelList.appendChild(rowFor(c)); });
    }
    if (grps.length) {
      $channelList.appendChild(groupLabel('채널', grps.length));
      grps.forEach(function (c) { $channelList.appendChild(rowFor(c)); });
    }

    // Sidebar sub-header: derive friend/online counts from /channels (no
    // presence API → online == DM count as a neutral default).
    if ($sideSub) {
      var n = dms.length;
      $sideSub.textContent = '친구 ' + n + ' · 온라인 ' + n;
    }
  }

  function loadChannels() {
    return fetch(apiBase() + '/channels', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { channels: [] }; })
      .then(function (data) {
        channels = (data && data.channels) || [];
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
        var ph = (c.name || c.channel) + '에게 메시지 보내기…';
        $input.setAttribute('data-ph', ph);
        $input.setAttribute('aria-label', (c.name || c.channel) + '에게 메시지 보내기');
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

  // ==== Connection (preserved) ====
  function wsUrl() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + location.host + apiBase() + '/ws';
  }
  function connect() {
    setStatus('connecting', '연결 중…');
    try {
      ws = new WebSocket(wsUrl());
    } catch (e) {
      setStatus('closed', '연결 실패');
      return;
    }
    ws.onopen = function () {
      setStatus('open', '연결됨');
      syncSendDisabled();
      try { ws.send(JSON.stringify({ type: 'ping', channel: CHANNEL, agent: AGENT })); } catch (e2) {}
    };
    ws.onmessage = function (ev) {
      var frame;
      try { frame = JSON.parse(ev.data); } catch (e) { return; }
      handleFrame(frame);
    };
    ws.onclose = function () {
      setStatus('closed', '연결 끊김');
      syncSendDisabled();
      showTyping(false);
    };
    ws.onerror = function () {
      setStatus('closed', '연결 오류');
    };
  }
  function reconnect() {
    if (ws) {
      try { ws.onclose = null; ws.close(); } catch (e) {}
      ws = null;
    }
    connect();
  }
  function sendText(text, replyToId) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    var frame = { type: 'text', channel: CHANNEL, agent: AGENT, text: text };
    // THREADS: reply_to passthrough — backend ignores unknown keys (safe), but
    // does NOT persist it (flagged follow-up). See top-of-file comment.
    if (replyToId != null) frame.reply_to = replyToId;
    ws.send(JSON.stringify(frame));
    return true;
  }

  // ==== Composer (2-tier contenteditable) ====
  function fieldText() {
    // Convert <div>/<br> line breaks to \n; contenteditable text.
    return ($input.innerText != null ? $input.innerText : $input.textContent || '')
      .replace(/ /g, ' ');
  }
  function clearField() { $input.innerHTML = ''; syncComposer(); }

  function syncSendDisabled() {
    var open = ws && ws.readyState === WebSocket.OPEN;
    var has = fieldText().trim().length > 0;
    if ($send) $send.disabled = !(open && has);
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

  function submitComposer() {
    var text = fieldText().trim();
    if (!text) return;
    var rt = replyTo ? replyTo.id : null;
    if (!sendText(text, rt)) return;  // gated on ws OPEN
    // Optimistic local echo of the owner's message — left-aligned grouped row.
    var ownerId = (channels[0] && channels[0]._ownerId) || '__owner';
    var m = frameToMsg(ownerId, OWNER_NAME, true, text, Date.now(), { replyTo: rt });
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
    $replyCueText.innerHTML = '<b>' + esc(src.name) + '</b> 님에게 답장 — ' + esc(replyTo.text.slice(0, 40));
    $input.focus();
  }
  function clearReplyCue() {
    replyTo = null;
    if ($replyCue) $replyCue.hidden = true;
  }
  if ($replyCueClear) $replyCueClear.addEventListener('click', clearReplyCue);

  // Delegated clicks for in-stream actions (reply / thread / quote jump).
  $stream.addEventListener('click', function (e) {
    var replyBtn = e.target.closest && e.target.closest('[data-reply]');
    if (replyBtn) { setReplyTo(replyBtn.getAttribute('data-reply')); return; }
    var threadBtn = e.target.closest && e.target.closest('[data-thread]');
    if (threadBtn) { openThreadPanel(threadBtn.getAttribute('data-thread')); return; }
    var jump = e.target.closest && e.target.closest('[data-jump]');
    if (jump) { jumpToMessage(jump.getAttribute('data-jump')); return; }
  });
  $stream.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var b = e.target.closest && e.target.closest('[data-reply],[data-thread]');
    if (!b) return;
    e.preventDefault();
    if (b.hasAttribute('data-reply')) setReplyTo(b.getAttribute('data-reply'));
    else openThreadPanel(b.getAttribute('data-thread'));
  });

  function jumpToMessage(id) {
    var el = $stream.querySelector('.msg[data-mid="' + cssEsc(id) + '"]');
    if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
  }

  // ==== Thread panel ====
  function renderThreadPanel(rootId) {
    var root = msgIndex[rootId];
    if (!root) return;
    var replies = threadsByRoot[rootId] || [];
    if ($threadSub) $threadSub.textContent = root.name + ' · 답글 ' + replies.length + '개';

    $threadBody.innerHTML = '';
    // Root rendered as a standalone lead row (no hover-pop in panel CSS).
    $threadBody.appendChild(threadRow(root, true));
    replies.forEach(function (r) { $threadBody.appendChild(threadRow(r, true)); });

    // Footer = a "reply to thread" affordance that seeds the reply-cue to root.
    $threadFoot.innerHTML = '';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tp-reply';
    btn.innerHTML = '<i class="ti ti-arrow-back-up" aria-hidden="true"></i><span>' +
      esc(root.name) + ' 님에게 답장</span>';
    btn.addEventListener('click', function () {
      setReplyTo(rootId);
      closeThreadPanel();
      $input.focus();
    });
    $threadFoot.appendChild(btn);
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
    if (!msgIndex[rootId]) return;
    openThreadRootId = rootId;
    lastFocused = document.activeElement;
    renderThreadPanel(rootId);
    $threadPanel.hidden = false;
    $threadPanel.setAttribute('aria-modal', isNarrow() ? 'true' : 'false');
    requestAnimationFrame(function () { $threadPanel.classList.add('open'); });
    if ($threadToggle) { $threadToggle.hidden = false; $threadToggle.classList.add('on'); }
    if ($threadClose) $threadClose.focus();
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

  // ==== Boot ====
  setChannelLabel('# ' + CHANNEL);
  loadChannels();
  loadHistory().then(function () { connect(); });
})();
