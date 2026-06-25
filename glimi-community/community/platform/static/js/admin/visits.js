// 방문 세션 admin — /api/admin/sessions 를 세션 카드 + 타임라인으로 렌더.
// path·체류·UA·IP 만. 조회는 admin 인증(서버에서 require_admin) 필수.
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function fmtDwell(ms) {
    if (!ms) return "—";
    var s = Math.round(ms / 1000);
    if (s < 60) return s + "s";
    var m = Math.floor(s / 60); var r = s % 60;
    return r ? m + "m " + r + "s" : m + "m";
  }

  function device(ua) {
    ua = ua || "";
    if (/iphone|android.*mobile|mobile/i.test(ua)) return "📱 모바일";
    if (/ipad|tablet/i.test(ua)) return "📱 태블릿";
    if (/bot|crawl|spider|curl|python|wget|monitor|uptime|headless/i.test(ua)) return "🤖 봇/체크";
    if (/macintosh|mac os/i.test(ua)) return "💻 Mac";
    if (/windows/i.test(ua)) return "💻 Windows";
    if (/linux/i.test(ua)) return "💻 Linux";
    return "💻 데스크톱";
  }

  function browser(ua) {
    ua = ua || "";
    if (/edg\//i.test(ua)) return "Edge";
    if (/chrome\//i.test(ua) && !/edg\//i.test(ua)) return "Chrome";
    if (/firefox\//i.test(ua)) return "Firefox";
    if (/safari\//i.test(ua) && !/chrome\//i.test(ua)) return "Safari";
    return "";
  }

  function fmtDate(iso) {
    if (!iso) return "";
    try {
      var d = new Date(iso);
      return d.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    } catch (e) { return iso.slice(0, 16).replace("T", " "); }
  }
  function fmtTime(iso) {
    if (!iso) return "";
    try { return new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
    catch (e) { return iso.slice(11, 19); }
  }

  function statsHtml(d) {
    var owner = d.owner_sessions || 0;
    return [
      ['<div class="vs-stat"><span class="n">', d.visitors || 0, '</span><span class="l">방문자</span></div>'].join(""),
      ['<div class="vs-stat"><span class="n">', (d.total || 0), '</span><span class="l">세션', owner ? " (+나 " + owner + ")" : "", '</span></div>'].join(""),
      ['<div class="vs-stat"><span class="n">', (d.sessions || []).reduce(function (a, s) { return a + (s.page_count || 0); }, 0), '</span><span class="l">페이지뷰</span></div>'].join(""),
    ].join("");
  }

  function cardHtml(s, i) {
    var geo = [s.city, s.country].filter(Boolean).join(", ");
    var isp = s.asorg || "";
    var meta = [device(s.ua), browser(s.ua), isp, geo].filter(Boolean).join(" · ");
    var badge = s.is_owner
      ? '<span class="vs-badge owner">나</span>'
      : (s.legacy ? '<span class="vs-badge legacy">추정</span>' : '<span class="vs-badge live">세션</span>');
    var evts = (s.events || []).map(function (e) {
      return ['<div class="vs-evt"><span class="t">', esc(fmtTime(e.ts)),
        '</span><span class="p" title="', esc(e.path), '">', esc(e.path || "/"),
        '</span><span class="d">', esc(fmtDwell(e.dwell_ms)), '</span></div>'].join("");
    }).join("");
    return [
      '<div class="vs-card', s.is_owner ? ' owner' : '', '" data-i="', i, '">',
      '  <div class="vs-card-head">',
      '    <div class="vs-who">', badge,
      '      <span class="vs-ip">', esc(s.ip || "(unknown)"), '</span>',
      '      <span class="vs-meta">', esc(meta), '</span>',
      '    </div>',
      '    <div class="vs-right">',
      '      <span class="vs-date">', esc(fmtDate(s.start_ts)), '</span>',
      '      <span>체류 <b>', esc(fmtDwell(s.total_dwell_ms)), '</b></span>',
      '      <span>페이지 <b>', (s.page_count || 0), '</b></span>',
      '      <span class="vs-caret">▶</span>',
      '    </div>',
      '  </div>',
      '  <div class="vs-timeline">', evts || '<div class="vs-meta" style="padding:6px 0">이벤트 없음</div>', '</div>',
      '</div>',
    ].join("");
  }

  function load() {
    var listEl = document.getElementById("vs-list");
    var statsEl = document.getElementById("vs-stats");
    fetch("/api/admin/sessions?limit=300", { credentials: "same-origin" })
      .then(function (r) {
        if (r.status === 401 || r.status === 403) throw new Error("admin 인증 필요");
        return r.json();
      })
      .then(function (d) {
        statsEl.innerHTML = statsHtml(d);
        var sess = d.sessions || [];
        if (!sess.length) {
          listEl.innerHTML = '<div class="vs-empty">아직 기록된 방문이 없어요. 공개 랜딩/데모 페이지를 둘러보면 여기 세션이 쌓입니다.</div>';
          return;
        }
        listEl.innerHTML = sess.map(cardHtml).join("");
        Array.prototype.forEach.call(listEl.querySelectorAll(".vs-card-head"), function (h) {
          h.addEventListener("click", function () { h.parentElement.classList.toggle("open"); });
        });
      })
      .catch(function (e) {
        listEl.innerHTML = '<div class="vs-empty">' + esc(e.message || "불러오기 실패") + '</div>';
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();
