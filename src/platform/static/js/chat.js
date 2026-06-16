// Glimi Web Chat — Phase 1. Single file, vanilla JS (matches dashboard.js style).
// Opens a WebSocket to the chat seam, sends text frames, renders incoming
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

  var ws = null;

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

  function setStatus(state, label) {
    if (!$status) return;
    $status.setAttribute('data-state', state);
    $status.textContent = label;
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

  // ==== Connection ====
  function wsUrl() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + location.host +
      '/community/' + encodeURIComponent(COMMUNITY) + '/chat/ws';
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

  connect();
})();
