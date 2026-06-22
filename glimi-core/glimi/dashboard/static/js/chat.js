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
  // Chat-client language. The chat client is separate from dashboard.js; mirror
  // its pick — localStorage override → <html lang> (server) → ko default — so the
  // composer / status / typing copy matches the dashboard chrome. Read once at
  // load (a live language toggle re-renders chrome immediately; chat copy follows
  // on the next load), so default to Korean (the primary audience).
  var LANG = (function () {
    var l = null;
    try { l = localStorage.getItem('glimi-lang'); } catch (e) {}
    l = l || (document.documentElement && document.documentElement.lang) || 'ko';
    return l === 'en' ? 'en' : 'ko';
  })();
  var EN = LANG === 'en';
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
  // lightbox (ships in _chat_shell.html → present on every chat surface)
  var $lightbox = document.getElementById('chat-lightbox');
  var $lightboxImg = document.getElementById('chat-lightbox-img');
  var $lightboxCap = document.getElementById('chat-lightbox-caption');
  var $lightboxClose = document.getElementById('chat-lightbox-close');
  // auto-run (workspace-only — toggle + status pill + brief modal). All inert
  // unless WS_BASE is truthy AND the surface isn't read-only (the demo).
  var $autorunToggle = document.getElementById('ws-autorun-toggle');
  var $autorunPill = document.getElementById('ws-autorun-pill');
  var $briefModal = document.getElementById('ws-brief-modal');
  var $briefClose = document.getElementById('ws-brief-close');
  var $briefCancel = document.getElementById('ws-brief-cancel');
  var $briefStart = document.getElementById('ws-brief-start');
  var $briefGoal = document.getElementById('ws-brief-goal');
  var $briefContext = document.getElementById('ws-brief-context');
  var $briefBacklog = document.getElementById('ws-brief-backlog');
  var $briefMaxRounds = document.getElementById('ws-brief-max-rounds');

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
  // ==== Backwards pagination (load older on scroll-to-top) ====
  // The smallest SERVER id currently loaded — the cursor for the next older page.
  var oldestLoadedId = null;
  var loadingOlder = false;  // re-entrancy guard for the scroll-up fetch
  var noMoreOlder = false;   // the server returned an empty older page → stop
  var HISTORY_PAGE = 50;     // page size for both cold-load + older pages
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
      .replace(/(^|\s)#([가-힣A-Za-z0-9_\-]+)/g, '$1<span class="ch" data-ch="$2">#$2</span>');
  }
  function escAttr(s) {
    return esc(s).replace(/"/g, '&quot;');
  }

  // ==== GFM-lite markdown renderer (dependency-free, XSS-safe) ====
  // CONTRACT: callers pass the RAW message text; mdToHtml escapes FIRST (esc),
  // then formats the escaped string. Because the input is fully entity-escaped
  // up front, the renderer can only ever emit a CLOSED set of tags it writes
  // itself (h1-3, strong, em, ul/ol/li, code, pre, a, p, br) plus the spans that
  // rich() re-introduces (@mention / #channel). No user-supplied markup survives:
  // a literal "<script>" in the message is "&lt;script&gt;" before any rule runs.
  // Links additionally pass through safeUrl() so only http(s)/mailto hrefs render.
  //
  // Supported: ATX headings (# .. ###), **bold**/__bold__, *italic*/_italic_,
  // `inline code`, ```fenced code```, - / * / + and 1. lists (one level),
  // [text](url) links + bare autolinks, blank-line paragraphs + soft line breaks.

  // Allow only safe link schemes; everything else (javascript:, data:, etc.) is
  // dropped so an [x](javascript:…) can't execute. Operates on the ESCAPED href
  // (so it sees "&amp;" etc.) and returns it re-quote-escaped for an attribute.
  function safeUrl(escapedHref) {
    var raw = (escapedHref || '').trim();
    // Decode the few entities esc() introduces so the scheme test sees the real
    // first chars, then re-check. We never inject this decoded form into HTML.
    var probe = raw.replace(/&amp;/g, '&').replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
    if (/^\s*(https?:|mailto:)/i.test(probe)) return raw.replace(/"/g, '&quot;');
    if (/^\s*(\/|#|\.\/|\?)/.test(probe)) return raw.replace(/"/g, '&quot;');  // relative/in-page
    if (/^[^:\s]+$/.test(probe)) return raw.replace(/"/g, '&quot;');           // bare host/path, no scheme
    return null;  // unsafe scheme → render the link text only, no <a>
  }

  // Inline formatting on an ALREADY-escaped string. Order matters: pull out
  // inline-code spans FIRST (placeholder them) so their contents are never
  // touched by bold/italic/mention rules, restore them last.
  function mdInline(s) {
    var codes = [];
    // `inline code` → placeholder (escaped backticks can't appear post-esc, so a
    // literal backtick in source is a real backtick here).
    s = s.replace(/`([^`]+)`/g, function (_m, c) {
      codes.push('<code class="md-code">' + c + '</code>');
      return ' ' + (codes.length - 1) + ' ';
    });
    // [text](url) links — text gets inline formatting, url is scheme-guarded.
    // URL part allows one level of balanced parens (e.g. a Wikipedia _(disambig)
    // link) so the whole "(…)" is consumed — no stray ")" leaks when a link is
    // dropped for an unsafe scheme.
    s = s.replace(/\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)/g, function (m, txt, url) {
      var href = safeUrl(url);
      if (!href) return txt;  // unsafe scheme → keep the visible text only
      return '<a class="md-link" href="' + href + '" target="_blank" rel="noopener noreferrer ugc">' + txt + '</a>';
    });
    // Bare autolinks (http/https) not already inside an <a …>.
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, function (m, pre, url) {
      var href = safeUrl(url);
      if (!href) return m;
      return pre + '<a class="md-link" href="' + href + '" target="_blank" rel="noopener noreferrer ugc">' + url + '</a>';
    });
    // Bold then italic (run bold first so ** isn't eaten by the * rule).
    s = s.replace(/\*\*([^]+?)\*\*/g, '<strong>$1</strong>')
         .replace(/__([^]+?)__/g, '<strong>$1</strong>')
         .replace(/(^|[^\*])\*(?!\s)([^*\n]+?)\*(?!\*)/g, '$1<em class="md-em">$2</em>')
         .replace(/(^|[^_\w])_(?!\s)([^_\n]+?)_(?![_\w])/g, '$1<em class="md-em">$2</em>');
    // @mention / #channel (and the legacy <em> marker) — reuse rich() so the
    // existing affordances keep working inside rendered markdown.
    s = rich(s);
    // Restore inline code.
    s = s.replace(/ (\d+) /g, function (_m, i) { return codes[Number(i)]; });
    return s;
  }

  // Block-level pass. ``escaped`` is the WHOLE message already run through esc().
  // Returns the inner HTML for a rendered markdown block.
  function mdBlocks(escaped) {
    var lines = String(escaped == null ? '' : escaped).split('\n');
    var out = [];
    var i = 0;
    var para = [];        // buffered consecutive text lines → one <p>
    function flushPara() {
      if (!para.length) return;
      out.push('<p>' + para.map(mdInline).join('<br>') + '</p>');
      para = [];
    }
    while (i < lines.length) {
      var line = lines[i];
      // Fenced code block ``` … ``` (lang tag after the opener is ignored).
      var fence = line.match(/^\s*```+\s*([^\s`]*)\s*$/);
      if (fence) {
        flushPara();
        var buf = [];
        i++;
        while (i < lines.length && !/^\s*```+\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
        i++;  // skip closing fence (or run off the end if unterminated)
        // Already escaped → emit verbatim, no inline rules inside code.
        out.push('<pre class="md-pre"><code>' + buf.join('\n') + '</code></pre>');
        continue;
      }
      // ATX heading (# .. ###; 4+ hashes degrade to h3).
      var h = line.match(/^\s*(#{1,6})\s+(.*)$/);
      if (h) {
        flushPara();
        var lvl = Math.min(h[1].length, 3);
        out.push('<h' + lvl + ' class="md-h md-h' + lvl + '">' + mdInline(h[2].trim()) + '</h' + lvl + '>');
        i++;
        continue;
      }
      // Unordered list (-, *, +) — consume the contiguous run.
      if (/^\s*[-*+]\s+/.test(line)) {
        flushPara();
        var ul = [];
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          ul.push('<li>' + mdInline(lines[i].replace(/^\s*[-*+]\s+/, '')) + '</li>');
          i++;
        }
        out.push('<ul class="md-list">' + ul.join('') + '</ul>');
        continue;
      }
      // Ordered list (1. 2. …) — consume the contiguous run.
      if (/^\s*\d+[.)]\s+/.test(line)) {
        flushPara();
        var ol = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          ol.push('<li>' + mdInline(lines[i].replace(/^\s*\d+[.)]\s+/, '')) + '</li>');
          i++;
        }
        out.push('<ol class="md-list">' + ol.join('') + '</ol>');
        continue;
      }
      // Blank line → paragraph break.
      if (/^\s*$/.test(line)) { flushPara(); i++; continue; }
      // Otherwise a normal text line → buffer into the current paragraph.
      para.push(line);
      i++;
    }
    flushPara();
    return out.join('');
  }

  // Public entry: RAW text → safe rendered-markdown HTML. Escape first (the XSS
  // boundary), then run the block + inline passes on the escaped text.
  function mdToHtml(raw) {
    return mdBlocks(esc(raw));
  }

  // Channel-mention system (works for Discord <#id> too): a #name in a message is
  // clickable and switches to that channel — resolved by real key, dm-<name>, or
  // the agent's display name, so #아린 / #dm-아린 / #서유나 all land on the right DM.
  function resolveChannelMention(raw) {
    var name = (raw || '').replace(/^#/, '');
    if (!name) return null;
    for (var i = 0; i < channels.length; i++) {
      var c = channels[i];
      if (c.channel === name) return c;
      if (c.channel === 'dm-' + name) return c;
      if ((c.name || '') === name) return c;
      if ((c.channel || '').replace(/^dm-/, '') === name) return c;
    }
    return null;
  }
  document.addEventListener('click', function (e) {
    var span = e.target && e.target.closest && e.target.closest('span.ch');
    if (!span) return;
    var target = resolveChannelMention(span.getAttribute('data-ch') || span.textContent);
    if (target) { e.preventDefault(); selectChannel(target); }
  });

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
  // Full-body portrait URL (variant=full) — same routing as avatarUrl() but asks
  // the avatar endpoint for the un-cropped full-body image used by the lightbox.
  function fullAvatarUrl(agentId) {
    return avatarUrl(agentId) + '&variant=full';
  }

  // ==== Lightbox (full-body profile / inline image) ====
  // Self-contained: depends ONLY on the #chat-lightbox markup shipped in
  // _chat_shell.html, NOT on dashboard.js / _core.html — so the standalone /chat
  // page (which loads only chat.js) opens the lightbox too.
  function openLightbox(src, caption) {
    if (!$lightbox || !$lightboxImg) return;
    $lightboxImg.src = src;
    $lightboxImg.alt = caption || '';
    if ($lightboxCap) $lightboxCap.textContent = caption || '';
    $lightbox.classList.add('open');
    $lightbox.setAttribute('aria-hidden', 'false');
    document.documentElement.classList.add('lb-open');  // lock body scroll
  }
  function closeLightbox() {
    if (!$lightbox) return;
    $lightbox.classList.remove('open');
    $lightbox.setAttribute('aria-hidden', 'true');
    document.documentElement.classList.remove('lb-open');
    if ($lightboxImg) { $lightboxImg.src = ''; }
  }
  // Open the FULL-BODY portrait for an agent. The owner has no portrait → no-op
  // (the message avatar there is a monogram, not an image).
  function openProfileLightbox(agentId, name) {
    if (!agentId) return;
    openLightbox(fullAvatarUrl(agentId), name || '');
  }
  if ($lightboxClose) $lightboxClose.addEventListener('click', closeLightbox);
  if ($lightbox) {
    // Click the dimmed backdrop (outside the panel) to close.
    $lightbox.addEventListener('click', function (e) {
      var panel = e.target.closest && e.target.closest('.lb-panel');
      if (!panel) closeLightbox();
    });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && $lightbox && $lightbox.classList.contains('open')) {
      e.stopPropagation();
      closeLightbox();
    }
  });

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

  // Display name for a channel. The server names internal-owner "오너의 검토"
  // (KO source); on the EN UI swap to "Owner's review" so the chrome stays
  // English. All other channels use the server-provided name verbatim.
  function channelDisplayName(c) {
    if (!c) return '';
    if (EN && c.channel === 'internal-owner') return "Owner's review";
    return c.name || c.channel || '';
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
  // For the MESSAGE-row avatar (cls 'av') a non-owner image is made clickable —
  // it opens the full-body portrait lightbox (data-* read by the $stream click
  // delegation). The owner avatar is a monogram (no portrait) → not clickable.
  // The sidebar rail avatar (cls 'ava') is NOT tagged here: its row already
  // routes a click to the DM (selectChannel), which is the right action there.
  function avHtml(speakerId, name, isUser, cls) {
    cls = cls || 'av';
    var clickable = (cls === 'av') && !isUser && !!speakerId;
    var dataAttrs = clickable
      ? ' data-profile-id="' + escAttr(speakerId) + '" data-profile-name="' + escAttr(name || '') +
        '" role="button" tabindex="0" title="' + escAttr(EN ? 'View profile' : '프로필 보기') + '"'
      : '';
    if (isUser) {
      return '<span class="' + cls + '" style="background:' + avBg(OWNER_NAME) + '">' + esc(initialOf(OWNER_NAME)) + '</span>';
    }
    if (speakerId) {
      return '<span class="' + cls + '"' + dataAttrs + ' style="background:' + avBg(speakerId) + '">' +
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
    var out = '';
    // Normal messages render as GFM-lite markdown (the whole blob is ONE
    // markdown document so multi-line replies get headings/lists/code/paragraphs).
    // System / error rows stay a plain pre-wrap line (short notices, no markdown).
    if (m.kind === 'sys' || m.kind === 'err') {
      out = m.lines.map(function (l) { return '<div class="txt">' + rich(esc(l)) + '</div>'; }).join('');
    } else if (m.lines && m.lines.length) {
      var body = mdToHtml(m.lines.join('\n'));
      if (body) out = '<div class="txt md">' + body + '</div>';
    }
    (m.images || []).forEach(function (im) {
      if (im && im.url) {
        out += '<img class="chat-img" src="' + escAttr(im.url) + '" alt="' + escAttr(im.caption || 'image') + '">';
        if (im.caption) out += '<div class="txt md">' + mdToHtml(im.caption) + '</div>';
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
    // Reset backwards-pagination cursor for the freshly opened channel.
    oldestLoadedId = null;
    loadingOlder = false;
    noMoreOlder = false;
  }
  // Track the smallest server id seen so the next older page can request before it.
  function noteOldest(id) {
    if (!isServerId(id)) return;
    var n = Number(id);
    if (oldestLoadedId == null || n < oldestLoadedId) oldestLoadedId = n;
  }

  // ==== Typing (typefoot + in-stream landing spot) ====
  function showTypeFoot(on, who) {
    if (!$typefoot) return;
    if (on) {
      if ($typefootWho) $typefootWho.textContent = who || (EN ? 'Someone' : '누군가');
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
      case 'auto':
        // Autonomous owner-driver lifecycle (workspace only). The owner
        // instruction + reasoning arrive as ordinary {type:'text'} frames and
        // render in their channels with zero extra logic; this just keeps the
        // toggle + status pill in sync with the loop's phase.
        handleAutoFrame(frame);
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
    var url = apiBase() + '/history?channel=' + encodeURIComponent(CHANNEL) + '&limit=' + HISTORY_PAGE;
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { messages: [] }; })
      .then(function (data) {
        clearStream();
        pinned = true;
        var msgs = (data && data.messages) || [];
        // Fewer than a full page means there's nothing older to fetch.
        if (msgs.length < HISTORY_PAGE) noMoreOlder = true;
        msgs.forEach(function (row) {
          noteOldest(row.id);
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

  // ==== Load older (scroll-to-top pagination) ====
  // Fetch the page of messages OLDER than oldestLoadedId and PREPEND it, keeping
  // the viewport visually stable (the row the user was looking at stays put).
  // Grouping is computed WITHIN the older batch (the seam to the existing first
  // row may show a fresh avatar — honest + cheap, no full re-render).
  function loadOlder() {
    if (loadingOlder || noMoreOlder || oldestLoadedId == null || !CHANNEL) return;
    loadingOlder = true;
    var cursor = oldestLoadedId;
    var url = apiBase() + '/history?channel=' + encodeURIComponent(CHANNEL) +
      '&limit=' + HISTORY_PAGE + '&before_id=' + encodeURIComponent(cursor);
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { messages: [] }; })
      .then(function (data) {
        var msgs = (data && data.messages) || [];
        // Dedup against what's already rendered (defensive — server pages by id).
        msgs = msgs.filter(function (row) {
          return row.id == null || !msgIndex[row.id];
        });
        if (!msgs.length) { noMoreOlder = true; return; }
        if (msgs.length < HISTORY_PAGE) noMoreOlder = true;
        prependOlder(msgs);
      })
      .catch(function () { /* transient — a later scroll-up retries */ })
      .then(function () { loadingOlder = false; });
  }

  // Build the older batch into a fragment (own grouping + day dividers) and insert
  // it before the current first child, then restore scrollTop so the viewport
  // doesn't jump.
  function prependOlder(msgs) {
    var frag = document.createDocumentFragment();
    var prev = null;  // grouping anchor WITHIN this batch
    msgs.forEach(function (row) {
      noteOldest(row.id);
      if (row.is_user && row.speaker_id && OWNER_ID == null) OWNER_ID = row.speaker_id;
      var rt = (row.reply_to && row.reply_to.id != null) ? row.reply_to.id : null;
      var m = frameToMsg(
        row.speaker_id, row.display_name || row.speaker_id || '',
        !!row.is_user, row.text || '', parseTs(row.timestamp),
        {
          id: row.id != null ? row.id : undefined,
          images: row.images || [], reactions: row.reactions || [],
          replyTo: rt, replyMeta: row.reply_to || null,
          threadRoot: row.thread_root != null ? row.thread_root : null
        }
      );
      msgIndex[m.id] = m;
      // Day divider when the day changes within the batch.
      var dayChanged = !prev || dateKeyOf(prev.ts) !== dateKeyOf(m.ts);
      if (dayChanged) {
        var div = document.createElement('div');
        div.className = 'daydiv';
        div.innerHTML = '<span class="ln"></span><span class="lb">' +
          esc(dayLabelOf(m.ts)) + '</span><span class="ln"></span>';
        frag.appendChild(div);
      }
      var isCont = !!prev && m.kind === 'msg' && prev.kind === 'msg' &&
        prev.speakerId === m.speakerId && prev.isUser === m.isUser &&
        (m.ts - prev.ts) <= GROUP_WINDOW && !dayChanged && m.replyTo == null;
      var el = buildRow(m, !isCont);
      el.classList.add('in');  // no enter animation on backfill
      frag.appendChild(el);
      prev = { speakerId: m.speakerId, isUser: m.isUser, ts: m.ts, kind: m.kind };
    });

    // Insert at the top + preserve scroll position (anchor on scrollHeight delta).
    var before = $feed.scrollHeight;
    var firstChild = $stream.firstChild;
    $stream.insertBefore(frag, firstChild);
    var after = $feed.scrollHeight;
    $feed.scrollTop += (after - before);

    // Now that older rows are indexed, refresh thread affordances on any roots
    // whose replies were loaded after them in this batch.
    msgs.forEach(function (row) {
      if (row.reply_to && row.reply_to.id != null) refreshThreadAffordance(String(row.reply_to.id));
    });
  }

  // Trigger an older-page fetch when the feed is scrolled near the very top.
  $feed.addEventListener('scroll', function () {
    if ($feed.scrollTop < 120) loadOlder();
  });

  // ==== Live poll ====
  // The WebSocket only carries messages that flow through THIS web process. The
  // Discord adapter (and any other transport) writes to the same DB in a separate
  // process, so those messages never hit the socket. Re-fetch the active channel's
  // tail on an interval and append only unseen ids (dedup via msgIndex; the owner's
  // own optimistic rows are already reconciled to their server id by the WS, so
  // they're skipped). This makes the chat live regardless of who wrote the message.
  function pollNew() {
    if (!CHANNEL) return;
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    var url = apiBase() + '/history?channel=' + encodeURIComponent(CHANNEL) + '&limit=50';
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { messages: [] }; })
      .then(function (data) {
        var msgs = (data && data.messages) || [];
        var added = false;
        msgs.forEach(function (row) {
          if (row.id == null || msgIndex[row.id]) return;  // unseen ids only
          if (row.is_user && row.speaker_id && OWNER_ID == null) OWNER_ID = row.speaker_id;
          var rt = (row.reply_to && row.reply_to.id != null) ? row.reply_to.id : null;
          appendMessage(frameToMsg(
            row.speaker_id, row.display_name || row.speaker_id || '',
            !!row.is_user, row.text || '', parseTs(row.timestamp),
            {
              id: row.id, images: row.images || [], reactions: row.reactions || [],
              replyTo: rt, replyMeta: row.reply_to || null,
              threadRoot: row.thread_root != null ? row.thread_root : null
            }
          ), true);
          if (rt != null) refreshThreadAffordance(String(rt));
          added = true;
        });
        if (added) updateChannelPreviewFromHistory(msgs);
      })
      .catch(function () { /* transient — next tick retries */ });
  }
  setInterval(pollNew, 3000);

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
  // `section` is a stable key ('groups'|'dms'|'internal') the onboarding tour
  // anchors on (header text is i18n/app-dependent, so never anchor by text).
  function groupLabel(text, count, section) {
    var li = document.createElement('li');
    li.className = 'grp-l' + (count === 0 || $channelList.children.length === 0 ? ' first' : '');
    if (section) li.dataset.section = section;
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
    } else if (c.kind === 'internal') {
      html += '<i class="ti ti-arrows-left-right hash" aria-hidden="true"></i>';
    } else {
      html += '<i class="ti ti-hash hash" aria-hidden="true"></i>';
    }
    var preview = c._preview ? '<span class="p">' + esc(c._preview) + '</span>' : '';
    html += '<span class="meta"><span class="t">' + esc(channelDisplayName(c)) + '</span>' + preview + '</span>';

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

  // Most-recent-activity sort key (DESC) for a channel: prefer the live preview ts
  // (set as the active channel updates), else the server-seeded last.timestamp.
  function activityTs(c) {
    if (c._ts) return c._ts;
    if (c.last && c.last.timestamp) return parseTs(c.last.timestamp) || 0;
    return 0;
  }
  function byRecencyDesc(a, b) {
    var d = activityTs(b) - activityTs(a);
    if (d) return d;
    // Stable tiebreak so equal-ts rows keep a deterministic order.
    return (a.name || a.channel || '').localeCompare(b.name || b.channel || '');
  }

  function renderChannels() {
    if (!$channelList) return;
    var q = ($search && $search.value || '').trim().toLowerCase();
    var match = function (c) {
      if (!q) return true;
      return (c.name || c.channel || '').toLowerCase().indexOf(q) !== -1;
    };
    // Discord/Slack ordering: group channels (rooms) FIRST, then DMs sorted by
    // most-recent activity, then the agent-to-agent backchannels ("Behind the
    // scenes"). Managers no longer get a separate pinned section — they sort by
    // recency like everyone else (the row still carries a manager tag/badge).
    var grps = channels.filter(function (c) { return c.kind === 'group' && match(c); })
      .sort(byRecencyDesc);
    var dms = channels.filter(function (c) { return c.kind === 'dm' && match(c); })
      .sort(byRecencyDesc);
    // agent-to-agent backchannels — the owner WATCHES (read-only). Core of Glimi:
    // friends talking to each other behind the scenes.
    var internal = channels.filter(function (c) { return c.kind === 'internal' && match(c); })
      .sort(byRecencyDesc);

    var ROOMS_LABEL = WS_BASE ? (EN ? 'Rooms' : '룸') : (EN ? 'Groups' : '그룹');
    var DMS_LABEL = WS_BASE ? (EN ? 'Team' : '팀') : (EN ? 'Direct messages' : '다이렉트 메시지');
    $channelList.innerHTML = '';
    if (grps.length) {
      $channelList.appendChild(groupLabel(ROOMS_LABEL, grps.length, 'groups'));
      grps.forEach(function (c) { $channelList.appendChild(rowFor(c)); });
    }
    if (dms.length) {
      $channelList.appendChild(groupLabel(DMS_LABEL, dms.length, 'dms'));
      dms.forEach(function (c) { $channelList.appendChild(rowFor(c)); });
    }
    if (internal.length) {
      $channelList.appendChild(groupLabel(EN ? 'Behind the scenes' : '에이전트끼리', internal.length, 'internal'));
      internal.forEach(function (c) { $channelList.appendChild(rowFor(c)); });
    }

    // Sidebar sub-header: friend/member count = persona DMs (managers excluded).
    if ($sideSub) {
      var n = dms.filter(function (c) { return c.agent_type === 'persona'; }).length;
      if (EN) {
        var noun = WS_BASE ? 'members' : 'friends';
        $sideSub.textContent = n + ' ' + noun + ' · ' + n + ' online';
      } else {
        $sideSub.textContent = n + '명 · ' + n + '명 접속 중';
      }
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
      setChannelLabel(channelDisplayName(c));
      if ($headIcon) {
        $headIcon.className = (c.kind === 'dm' ? 'ti ti-at hash'
          : c.kind === 'internal' ? 'ti ti-arrows-left-right hash' : 'ti ti-hash hash');
      }
      if ($input) {
        var nm = channelDisplayName(c);
        if (c.postable === false) {
          $input.setAttribute('data-ph', EN ? "Read-only — you're watching" : '관전 전용 — 에이전트끼리 대화');
          $input.setAttribute('aria-label', EN ? 'Read-only channel' : '관전 전용 채널');
        } else {
          $input.setAttribute('data-ph', EN ? ('Message ' + nm + '…') : (nm + '에게 메시지…'));
          $input.setAttribute('aria-label', EN ? ('Message ' + nm) : (nm + '에게 메시지'));
        }
      }
    } else {
      setChannelLabel('# ' + CHANNEL);
    }
    applyChannelComposerState();
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
  // Mobile: the channel header doubles as the channel switcher — tapping the
  // title / icon / ⌄ cue opens the drawer (the small hamburger alone was hard to
  // discover on phones). No-op on desktop where the sidebar is always present.
  function headTapNav() { if (isNarrow()) openSidebarMobile(); }
  if ($channelLabel) $channelLabel.addEventListener('click', headTapNav);
  if ($headIcon) $headIcon.addEventListener('click', headTapNav);
  var $headNavCue = document.getElementById('chat-head-nav-cue');
  if ($headNavCue) $headNavCue.addEventListener('click', headTapNav);
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
    setStatus('connecting', EN ? 'Reconnecting…' : '다시 연결 중…');
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connect();
    }, delay);
  }
  function connect() {
    intentionalClose = false;
    setStatus('connecting', EN ? 'Connecting…' : '연결 중…');
    try {
      ws = new WebSocket(wsUrl());
    } catch (e) {
      setStatus('closed', 'Connection failed');
      scheduleReconnect();
      return;
    }
    ws.onopen = function () {
      reconnectAttempts = 0;
      setStatus('open', EN ? 'Connected' : '연결됨');
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

  function currentChannelObj() {
    for (var i = 0; i < channels.length; i++) {
      if (channels[i].channel === CHANNEL) return channels[i];
    }
    return null;
  }
  function chanReadonly() {
    var c = currentChannelObj();
    return !!(c && c.postable === false);
  }
  // Per-channel composer lock — internal (agent-to-agent) channels are watch-only
  // even in a non-demo community. Distinct from the demo-wide READONLY.
  function applyChannelComposerState() {
    if (READONLY) return;  // demo-wide lock already applied
    var ro = chanReadonly();
    if ($input) {
      $input.setAttribute('contenteditable', ro ? 'false' : 'true');
      if (ro) $input.setAttribute('aria-disabled', 'true');
      else $input.removeAttribute('aria-disabled');
    }
    var composer = $cbox ? $cbox.closest('.composer') : null;
    if (composer) composer.classList.toggle('readonly', ro);
    if ($cbox) $cbox.classList.toggle('readonly', ro);
    syncSendDisabled();
  }

  function syncSendDisabled() {
    if (READONLY || chanReadonly()) { if ($send) $send.disabled = true; return; }
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
  // Coarse pointer (touch): the action-pop is hover-hidden (no flash on scroll),
  // so reveal it on an explicit TAP of the message row instead. One row open at a
  // time; tapping elsewhere (or a fresh tap on the same row) closes it.
  var COARSE = !!(window.matchMedia && window.matchMedia('(hover: none)').matches);
  function closeActsOpen(except) {
    var open = $stream.querySelectorAll('.msg.acts-open');
    for (var i = 0; i < open.length; i++) {
      if (open[i] !== except) open[i].classList.remove('acts-open');
    }
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
    // A message-row avatar opens the speaker's FULL-BODY portrait lightbox
    // (distinct from the sidebar row, which opens the DM).
    var prof = e.target.closest && e.target.closest('[data-profile-id]');
    if (prof) {
      e.preventDefault(); e.stopPropagation();
      openProfileLightbox(prof.getAttribute('data-profile-id'), prof.getAttribute('data-profile-name'));
      return;
    }
    // An inline content image opens in the lightbox at its own src (real image,
    // not an avatar → no variant=full upgrade).
    var cimg = e.target.closest && e.target.closest('img.chat-img');
    if (cimg) {
      e.preventDefault(); e.stopPropagation();
      openLightbox(cimg.getAttribute('src'), cimg.getAttribute('alt') || '');
      return;
    }
    // Touch: a bare tap on a message row (not a link/button/image/pill) toggles
    // its action-pop so react/reply/thread are reachable without a hover.
    if (COARSE) {
      if (e.target.closest && e.target.closest('a, button, b, img, .acts-pop, .react, .quote, .ch, .mention')) return;
      var row = e.target.closest && e.target.closest('.msg[data-mid]');
      if (!row || row.classList.contains('sys') || row.classList.contains('err')) { closeActsOpen(null); return; }
      var wasOpen = row.classList.contains('acts-open');
      closeActsOpen(row);
      row.classList.toggle('acts-open', !wasOpen);
    }
  });
  // Touch: tapping anywhere outside the message stream closes an open action-pop.
  if (COARSE) {
    document.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('#chat-stream .msg')) return;
      closeActsOpen(null);
    });
  }
  $stream.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var prof = e.target.closest && e.target.closest('[data-profile-id]');
    if (prof) {
      e.preventDefault();
      openProfileLightbox(prof.getAttribute('data-profile-id'), prof.getAttribute('data-profile-name'));
      return;
    }
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
      $threadSub.textContent = (root ? (root.name + ' · ') : '') + (EN ? (replyCount + (replyCount === 1 ? ' reply' : ' replies')) : (replyCount + '개의 답글'));
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
    if ($threadSub) $threadSub.textContent = EN ? 'Loading…' : '불러오는 중…';
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

  // ==== Auto-run (workspace autonomous owner-driver) ====
  // The work-clone analogue of the Community's autonomous social sim: the owner
  // hands the team a goal + brief, then the loop runs goal→work→review→next on
  // its own. This UI half is the toggle (header), the brief modal, and a status
  // pill. EVERYTHING here is inert unless WS_BASE is truthy AND the surface isn't
  // read-only — chat.js keys app mode off WS_BASE (Community/kernel never see it),
  // and the demo (READONLY) never exposes it (the demo showcases via a scripted
  // loop, never the live driver — POST /auto/start 403s there anyway).
  var AUTORUN_ENABLED = !!WS_BASE && !READONLY;
  var autoState = { running: false, auto_run: false, rounds_run: 0, max_rounds: 5, goal: '' };
  var autoPollTimer = null;

  function autorunUrl(path) { return WS_BASE + '/auto/' + path; }

  // Reveal the toggle for the workspace surface only. Called once after boot.
  function initAutorunUi() {
    if (!AUTORUN_ENABLED) return;  // toggle stays hidden (default) everywhere else
    if ($autorunToggle) {
      $autorunToggle.hidden = false;
      $autorunToggle.addEventListener('click', onToggleClick);
    }
    bindBriefModal();
    // Restore state on load (toggle reflects auto_run; pill shows if running).
    refreshAutoStatus();
    // Light poll so the toggle/pill recover if the loop ends while the owner is
    // on another channel (the per-ws WS fan-out also pushes {type:'auto'} frames,
    // but the poll is the belt-and-suspenders restore on tab re-entry / reconnect).
    if (autoPollTimer) clearInterval(autoPollTimer);
    autoPollTimer = setInterval(function () {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      refreshAutoStatus();
    }, 5000);
  }

  function onToggleClick() {
    if (!AUTORUN_ENABLED) return;
    if (autoState.running) {
      stopAutorun();
    } else {
      openBriefModal();
    }
  }

  // GET /auto/status → reflect running/auto_run/rounds into the toggle + pill.
  // The status endpoint is the source of truth for the terminal reset: a
  // max_rounds exit fires NO {type:'auto'} WS frame (the loop just ends), so the
  // poll is what flips the toggle back off. A running→idle edge also refreshes
  // the channel list (the loop may have created internal-owner).
  function refreshAutoStatus() {
    if (!AUTORUN_ENABLED) return;
    fetch(autorunUrl('status'), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        var wasRunning = autoState.running;
        autoState.running = !!d.running;
        autoState.auto_run = !!d.auto_run;
        autoState.rounds_run = d.rounds_run || 0;
        autoState.max_rounds = d.max_rounds || autoState.max_rounds;
        renderAutoToggle();
        // Edge transition (idle→running OR running→idle): the loop created
        // internal-owner on round 1 and may have ended — re-pull the channel
        // list so "오너의 검토" appears / preview updates without a manual refresh.
        if (wasRunning !== autoState.running) loadChannels();
      })
      .catch(function () { /* transient — next tick retries */ });
  }

  // Pull goal + a persisted brief from the snapshot so the modal prefills.
  function loadAutoBrief() {
    fetch(WS_BASE + '/api/snapshot', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        var a = d.auto || {};
        var cm = d.community_meta || {};
        autoState.goal = a.goal || cm.name || '';
        if ($briefGoal) $briefGoal.value = autoState.goal;
        if ($briefMaxRounds && a.max_rounds) $briefMaxRounds.value = a.max_rounds;
        if ($briefContext && a.context && !$briefContext.value) $briefContext.value = a.context;
        if ($briefBacklog && a.backlog && a.backlog.length && !$briefBacklog.value) {
          $briefBacklog.value = a.backlog.join('\n');
        }
      })
      .catch(function () { /* leave the modal defaults */ });
  }

  // Toggle visual state: pressed + accent while running, plain otherwise. The
  // header icon flips play↔stop; the pill shows the live round count.
  function renderAutoToggle() {
    if (!$autorunToggle) return;
    var running = autoState.running;
    $autorunToggle.setAttribute('aria-pressed', running ? 'true' : 'false');
    $autorunToggle.classList.toggle('on', running);
    var ico = $autorunToggle.querySelector('i');
    if (ico) ico.className = (running ? 'ti ti-player-stop' : 'ti ti-player-play');
    var lbl = running ? (EN ? 'Stop' : '중지') : (EN ? 'Auto-run' : '자동 진행');
    $autorunToggle.setAttribute('aria-label', lbl);
    $autorunToggle.setAttribute('title', lbl);
    renderAutoPill();
  }
  function renderAutoPill() {
    if (!$autorunPill) return;
    if (autoState.running) {
      var n = autoState.rounds_run || 0;
      $autorunPill.hidden = false;
      $autorunPill.classList.add('show');
      $autorunPill.textContent = EN
        ? ('Running' + (n ? ' · round ' + n : '…'))
        : ('자동 진행 중' + (n ? ' · 라운드 ' + n : '…'));
    } else {
      $autorunPill.classList.remove('show');
      $autorunPill.hidden = true;
      $autorunPill.textContent = '';
    }
  }

  // {type:'auto', phase} frames from the live driver fan-out. round_done bumps
  // the pill; terminal phases flip the toggle off + surface a brief status.
  function handleAutoFrame(frame) {
    if (!AUTORUN_ENABLED) return;
    var phase = frame && frame.phase;
    switch (phase) {
      case 'round_done':
        autoState.running = true;
        autoState.rounds_run = frame.round || autoState.rounds_run;
        renderAutoToggle();
        break;
      case 'done':
      case 'cancelled':
      case 'budget_exhausted':
      case 'error':
        autoState.running = false;
        autoState.auto_run = false;
        renderAutoToggle();
        flashAutoStatus(phase);
        loadChannels();  // refresh previews / surface internal-owner
        break;
      default:
        // Any other auto phase still means the loop is live — keep the pill on.
        autoState.running = true;
        renderAutoToggle();
        break;
    }
  }
  // A brief, self-clearing pill message on terminal phases (no toast dependency).
  function flashAutoStatus(phase) {
    if (!$autorunPill) return;
    var msg = phase === 'done' ? (EN ? 'Done' : '완료')
      : phase === 'budget_exhausted' ? (EN ? 'Budget reached' : '예산 한도')
      : phase === 'error' ? (EN ? 'Stopped' : '중단됨')
      : (EN ? 'Stopped' : '중지됨');
    $autorunPill.hidden = false;
    $autorunPill.classList.add('show');
    $autorunPill.textContent = msg;
    setTimeout(function () {
      if (!autoState.running) { $autorunPill.classList.remove('show'); $autorunPill.hidden = true; }
    }, 4000);
  }

  // ==== Brief modal ====
  function bindBriefModal() {
    if ($briefClose) $briefClose.addEventListener('click', closeBriefModal);
    if ($briefCancel) $briefCancel.addEventListener('click', closeBriefModal);
    if ($briefStart) $briefStart.addEventListener('click', submitBrief);
    if ($briefModal) {
      // Click the dimmed backdrop (outside the panel) to close.
      $briefModal.addEventListener('click', function (e) {
        var panel = e.target.closest && e.target.closest('.wbm-panel');
        if (!panel) closeBriefModal();
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && $briefModal && !$briefModal.hidden) {
        e.stopPropagation();
        closeBriefModal();
      }
    });
  }
  function openBriefModal() {
    if (!$briefModal) return;
    loadAutoBrief();  // prefill goal + any persisted brief
    $briefModal.hidden = false;
    $briefModal.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(function () { $briefModal.classList.add('open'); });
    if ($briefContext) { try { $briefContext.focus(); } catch (e) {} }
  }
  function closeBriefModal() {
    if (!$briefModal) return;
    $briefModal.classList.remove('open');
    $briefModal.setAttribute('aria-hidden', 'true');
    setTimeout(function () { if (!$briefModal.classList.contains('open')) $briefModal.hidden = true; }, 200);
  }

  // POST /auto/start with the brief. Body matches the server contract:
  // {context?, backlog?:[str]|str, max_rounds?} — goal lives on the workspace.
  function submitBrief() {
    if (!AUTORUN_ENABLED) return;
    var context = $briefContext ? $briefContext.value.trim() : '';
    var backlog = $briefBacklog
      ? $briefBacklog.value.split('\n').map(function (s) { return s.trim(); })
          .filter(function (s) { return s.length; })
      : [];
    var maxRounds = 5;
    if ($briefMaxRounds) {
      var v = parseInt($briefMaxRounds.value, 10);
      if (!isNaN(v)) maxRounds = Math.max(1, Math.min(v, 10));
    }
    if ($briefStart) $briefStart.disabled = true;
    fetch(autorunUrl('start'), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ context: context, backlog: backlog, max_rounds: maxRounds })
    })
      .then(function (r) { return r.ok ? r.json() : r.json().catch(function () { return { ok: false }; }); })
      .then(function (d) {
        if (d && d.ok) {
          autoState.running = true;
          autoState.auto_run = true;
          autoState.rounds_run = 0;
          autoState.max_rounds = d.max_rounds || maxRounds;
          renderAutoToggle();
          closeBriefModal();
          // The driver creates internal-owner on round 1 — re-pull the channel
          // list shortly after so "오너의 검토" appears in the sidebar.
          setTimeout(loadChannels, 1500);
        }
      })
      .catch(function () { /* leave the modal open so the owner can retry */ })
      .then(function () { if ($briefStart) $briefStart.disabled = false; });
  }

  // POST /auto/stop (idempotent). Optimistically flip off; status reconciles.
  function stopAutorun() {
    if (!AUTORUN_ENABLED) return;
    autoState.running = false;
    autoState.auto_run = false;
    renderAutoToggle();
    fetch(autorunUrl('stop'), { method: 'POST', credentials: 'same-origin' })
      .catch(function () { /* the loop is also externally bounded; status reconciles */ })
      .then(function () { refreshAutoStatus(); });
  }

  // ==== Boot / public API ====
  // The DOM consts + listener bindings above run ONCE at load (idempotent, bind
  // to the single #view-chat / chat.html instance). Only the data-loading boot
  // (channel list + history cold-load + WS connect) is deferred behind init() so
  // the embedded dashboard can lazy-start it on first Chat-tab entry.
  var _inited = false;
  function _boot() {
    setChannelLabel('# ' + CHANNEL);
    loadChannels().then(function () {
      // If the seeded default channel isn't a real one (every community seeds the
      // same 'dm-mgr' default, but a real community's manager DM is keyed by the
      // manager's id/name — e.g. 'dm-서유나' — so 'dm-mgr' is absent), fall back to
      // a real channel so the chat opens on a live conversation, not a blank pane.
      // Prefer the first POSTABLE channel (a DM/group the owner can open) over a
      // read-only internal backchannel, so high-volume communities whose only
      // 'dm-mgr' is absent still land on their busiest real DM.
      if (channels.length && !channels.some(function (x) { return x.channel === CHANNEL; })) {
        var c = null;
        for (var i = 0; i < channels.length; i++) {
          if (channels[i].postable !== false) { c = channels[i]; break; }
        }
        if (!c) c = channels[0];  // all read-only → at least show one
        CHANNEL = c.channel;
        AGENT = c.agent_id || AGENT;
        renderChannels();
        syncHead();
      }
      loadHistory().then(function () { connect(); });
    });
    // Workspace-only: reveal + wire the auto-run toggle / brief modal (no-op
    // everywhere else — Community/kernel never have WS_BASE, the demo is read-only).
    initAutorunUi();
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
    // Graph NODE→chat jump: resolve an agent_id to its DM channel from the loaded
    // channel list (the web DM key is opaque — dm-<id> in workspace, dm-<name> in
    // community — so match on the channel's agent_id, never reconstruct the key).
    // Returns the channel id, or null when the agent has no DM listed.
    channelForAgent: function (agentId) {
      if (!agentId) return null;
      for (var i = 0; i < channels.length; i++) {
        if (channels[i].kind === 'dm' && channels[i].agent_id === agentId) {
          return channels[i].channel;
        }
      }
      return null;
    },
    // Graph NODE→chat jump: open the agent's DM. Resolves the channel from the
    // loaded list; falls back to dm-<id> if the list isn't loaded yet (boot path).
    openAgentChannel: function (agentId) {
      if (!agentId) return;
      var ch = window.GlimiChat.channelForAgent(agentId) || ('dm-' + agentId);
      window.GlimiChat.selectChannelById(ch, agentId);
    },
    // Re-entry into the Chat tab: re-pin the feed to bottom (the WS is untouched).
    refit: function () { if ($feed) { pinned = true; $feed.scrollTop = $feed.scrollHeight; } }
  };

  // Standalone /chat auto-boots; embedded dashboard lazy-inits on first tab entry.
  if (!EMBEDDED) window.GlimiChat.init();
})();
