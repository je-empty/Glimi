// Glimi Web Chat — Phase 2. Single file, vanilla JS (matches dashboard.js style).
// Channel list (DM-per-agent + groups), history cold-load on open, and a single
// WebSocket to the chat seam that is (re)connected per selected channel. Renders
// text/typing/image/interrupted/error frames into the message list.
(function () {
  'use strict';

  // ==== State (injected by template, URL fallback) ====
  var params = new URLSearchParams(location.search);
  var COMMUNITY = window.__GLIMI_COMMUNITY__ || params.get('community') || '';
  var CHANNEL = window.__GLIMI_CHANNEL__ || params.get('channel') || '';
  var AGENT = window.__GLIMI_AGENT__ || params.get('agent') || 'mgr';

  var THEME = localStorage.getItem('glimi-theme') || 'light';
  document.documentElement.setAttribute('data-theme', THEME);

  var $messages = document.getElementById('chat-messages');
  var $form = document.getElementById('chat-composer');
  var $input = document.getElementById('chat-input');
  var $send = document.getElementById('chat-send');
  var $status = document.getElementById('chat-status');
  var $typing = document.getElementById('chat-typing');
  var $typingWho = document.getElementById('chat-typing-who');
  var $channelLabel = document.getElementById('chat-channel-label');
  var $channelList = document.getElementById('chat-channel-list');
  var $sidebar = document.getElementById('chat-sidebar');
  var $sidebarToggle = document.getElementById('chat-sidebar-toggle');

  var ws = null;
  var channels = [];

  // ==== Small helpers ====
  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function apiBase() {
    return '/community/' + encodeURIComponent(COMMUNITY) + '/chat';
  }

  function avatarUrl(agentId) {
    return '/api/avatar?id=' + encodeURIComponent(agentId) +
      (COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : '');
  }

  // ==== Rendering ====
  function scrollToBottom() {
    $messages.scrollTop = $messages.scrollHeight;
  }

  function appendMessage(kind, who, render) {
    var wrap = document.createElement('div');
    wrap.className = 'chat-msg is-' + kind;
    if (who && (kind === 'agent' || kind === 'user')) {
      var w = document.createElement('div');
      w.className = 'chat-msg-who';
      w.textContent = who;
      wrap.appendChild(w);
    }
    var bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    render(bubble);
    wrap.appendChild(bubble);
    $messages.appendChild(wrap);
    scrollToBottom();
  }

  function addText(kind, who, text) {
    appendMessage(kind, who, function (bubble) { bubble.textContent = text; });
  }

  function addImage(who, url, caption) {
    appendMessage('agent', who, function (bubble) {
      if (url) {
        var img = document.createElement('img');
        img.className = 'chat-img';
        img.src = url;
        img.alt = caption || 'image';
        bubble.appendChild(img);
      }
      if (caption) {
        var cap = document.createElement('div');
        cap.textContent = caption;
        bubble.appendChild(cap);
      }
    });
  }

  function clearMessages() {
    $messages.innerHTML = '';
  }

  function setStatus(state, label) {
    if (!$status) return;
    $status.setAttribute('data-state', state);
    $status.textContent = label;
  }

  function setChannelLabel(text) {
    if ($channelLabel) $channelLabel.textContent = text;
  }

  function showTyping(on, who) {
    if (!$typing) return;
    if (on) {
      $typing.hidden = false;
      if ($typingWho) $typingWho.textContent = who ? (who + ' 입력 중…') : '입력 중…';
    } else {
      $typing.hidden = true;
    }
  }

  // ==== Frame handling ====
  function handleFrame(frame) {
    var type = frame && frame.type;
    // Only render frames for the active channel (the socket may briefly carry
    // frames during a switch).
    if (frame && frame.channel && frame.channel !== CHANNEL) return;
    switch (type) {
      case 'text':
        addText('agent', frame.speaker || frame.agent_id || '', frame.text || '');
        break;
      case 'typing':
        showTyping(!!frame.on, frame.speaker || frame.agent_id || '');
        break;
      case 'image':
        addImage(frame.speaker || frame.agent_id || '', frame.url || '', frame.caption || '');
        break;
      case 'interrupted':
        addText('system', null, (frame.speaker || '상대') + '의 응답이 중단되었습니다.');
        break;
      case 'error':
        showTyping(false);
        addText('error', null, frame.error || '오류가 발생했습니다.');
        break;
      case 'pong':
        break;
      default:
        // Unknown frame — ignore quietly.
        break;
    }
  }

  // ==== History cold-load ====
  function loadHistory() {
    var url = apiBase() + '/history?channel=' + encodeURIComponent(CHANNEL) + '&limit=50';
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { messages: [] }; })
      .then(function (data) {
        clearMessages();
        var msgs = (data && data.messages) || [];
        msgs.forEach(function (m) {
          if (m.is_user) {
            addText('user', null, m.text || '');
          } else {
            addText('agent', m.display_name || m.speaker_id || '', m.text || '');
          }
        });
        scrollToBottom();
      })
      .catch(function () { /* leave whatever is shown */ });
  }

  // ==== Channel list ====
  function renderChannels() {
    if (!$channelList) return;
    $channelList.innerHTML = '';
    channels.forEach(function (c) {
      var li = document.createElement('li');
      li.className = 'chat-channel-item' + (c.channel === CHANNEL ? ' is-active' : '');
      li.setAttribute('role', 'button');
      li.tabIndex = 0;
      li.dataset.channel = c.channel;
      li.dataset.agent = c.agent_id || '';

      if (c.kind === 'dm' && c.agent_id) {
        var img = document.createElement('img');
        img.className = 'chat-channel-avatar';
        img.src = avatarUrl(c.agent_id);
        img.alt = '';
        li.appendChild(img);
      } else {
        var ph = document.createElement('span');
        ph.className = 'chat-channel-avatar is-group';
        ph.textContent = '#';
        li.appendChild(ph);
      }

      var name = document.createElement('span');
      name.className = 'chat-channel-name';
      name.textContent = c.name || c.channel;
      li.appendChild(name);

      li.addEventListener('click', function () { selectChannel(c); });
      li.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectChannel(c); }
      });
      $channelList.appendChild(li);
    });
  }

  function loadChannels() {
    return fetch(apiBase() + '/channels', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { channels: [] }; })
      .then(function (data) {
        channels = (data && data.channels) || [];
        // If the current channel isn't in the list, keep it (seeded default);
        // otherwise sync the active highlight.
        renderChannels();
      })
      .catch(function () { /* no sidebar data */ });
  }

  function selectChannel(c) {
    if (!c || c.channel === CHANNEL) { closeSidebarMobile(); return; }
    CHANNEL = c.channel;
    AGENT = c.agent_id || AGENT;
    setChannelLabel('# ' + CHANNEL);
    renderChannels();
    closeSidebarMobile();
    // Cold-load history, then (re)connect the socket to the new channel.
    loadHistory().then(function () { reconnect(); });
  }

  // ==== Sidebar (mobile toggle) ====
  function closeSidebarMobile() {
    if ($sidebar) $sidebar.classList.remove('is-open');
    if ($sidebarToggle) $sidebarToggle.setAttribute('aria-expanded', 'false');
  }
  if ($sidebarToggle && $sidebar) {
    $sidebarToggle.addEventListener('click', function () {
      var open = $sidebar.classList.toggle('is-open');
      $sidebarToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // ==== Connection ====
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
      if ($send) $send.disabled = false;
      // Register this socket for the active channel (a no-text frame would be
      // rejected, so registration happens lazily on the first send; we ping to
      // keep the seam aware of liveness).
      try { ws.send(JSON.stringify({ type: 'ping', channel: CHANNEL, agent: AGENT })); } catch (e2) {}
    };
    ws.onmessage = function (ev) {
      var frame;
      try { frame = JSON.parse(ev.data); } catch (e) { return; }
      handleFrame(frame);
    };
    ws.onclose = function () {
      setStatus('closed', '연결 끊김');
      if ($send) $send.disabled = true;
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

  function sendText(text) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: 'text', channel: CHANNEL, agent: AGENT, text: text }));
    return true;
  }

  // ==== Composer ====
  if ($form) {
    $form.addEventListener('submit', function (e) {
      e.preventDefault();
      var text = ($input.value || '').trim();
      if (!text) return;
      if (sendText(text)) {
        addText('user', null, text);
        $input.value = '';
        $input.focus();
      }
    });
  }

  // ==== Boot ====
  setChannelLabel('# ' + CHANNEL);
  loadChannels();
  loadHistory().then(function () { connect(); });
})();
