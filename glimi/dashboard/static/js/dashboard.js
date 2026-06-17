/* ============================================================
   Glimi Core dashboard — store-driven, read-only (P1.1)

   Drives a focused dashboard against three read-only endpoints
   backed by glimi.dashboard.reader.DashboardReader:
     GET /api/snapshot              → graph + KPIs + agent grid + channels
     GET /api/agent_detail?id=...   → agent modal (profile + memory + facts + rels)
     GET /api/channel?name=...      → channel viewer (participants + messages)

   The connection graph reuses the Community dashboard's Cytoscape
   approach (concentric layout, avatar-less node styling, channel
   edges + relationship edges) but is fed entirely by the store
   snapshot — no Discord / Community / server-control assumptions.
   ============================================================ */
(function () {
  "use strict";

  // ── small helpers ────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  async function fetchJson(url) {
    try {
      const r = await fetch(url);
      if (!r.ok) return null;
      return await r.json();
    } catch (_) {
      return null;
    }
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString();
  }

  const TYPE_RANK = { mgr: 0, creator: 1, dev: 2, persona: 3 };
  const TYPE_COLOR = {
    mgr: "--mgr",
    creator: "--creator",
    dev: "--dev",
    persona: "--persona",
  };

  // ── theme toggle ─────────────────────────────────────
  function initTheme() {
    const saved = localStorage.getItem("glimi-theme") || "light";
    document.documentElement.setAttribute("data-theme", saved);
    const btn = $("theme-toggle");
    if (btn) {
      btn.textContent = saved === "dark" ? "☀ Light" : "☾ Dark";
      btn.addEventListener("click", () => {
        const cur = document.documentElement.getAttribute("data-theme");
        const next = cur === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("glimi-theme", next);
        btn.textContent = next === "dark" ? "☀ Light" : "☾ Dark";
        if (window.__GLIMI_SNAP__) mountGraph(window.__GLIMI_SNAP__);
      });
    }
  }

  // ── connection graph (Cytoscape) ─────────────────────
  let cyInstance = null;

  function buildGraphElements(snap) {
    const agents = snap.agents || [];
    const channels = snap.channels || [];
    const relationships = snap.relationships || [];
    const idToAgent = {};
    for (const a of agents) idToAgent[a.id] = a;

    const involved = new Set();
    // mgr / creator always shown
    for (const a of agents) {
      if (a.type === "mgr" || a.type === "creator") involved.add(a.id);
    }

    // Channel-derived edges: every participant pair in an active channel.
    const rawEdges = [];
    let ownerInvolved = false;
    for (const c of channels) {
      const parts = [];
      for (const pid of c.participants || []) {
        if (idToAgent[pid]) {
          parts.push(pid);
          involved.add(pid);
        } else if (pid && !idToAgent[pid]) {
          // a non-agent participant = the owner / user end of the channel
          parts.push("__owner__");
          ownerInvolved = true;
        }
      }
      // dedupe owner pushes
      const uniq = Array.from(new Set(parts));
      if (uniq.length < 2) continue;
      const msgCount = c.msg_count || 0;
      for (let i = 0; i < uniq.length; i++) {
        for (let j = i + 1; j < uniq.length; j++) {
          rawEdges.push({
            source: uniq[i],
            target: uniq[j],
            channel: c.channel,
            kind: "channel",
            msgCount,
          });
        }
      }
    }

    // Relationship edges (from the store's relationship graph).
    for (const r of relationships) {
      const s = r.source;
      const t = r.target;
      if (idToAgent[s]) involved.add(s);
      if (idToAgent[t]) involved.add(t);
      const sOwner = !idToAgent[s];
      const tOwner = !idToAgent[t];
      if (sOwner || tOwner) ownerInvolved = true;
      rawEdges.push({
        source: sOwner ? "__owner__" : s,
        target: tOwner ? "__owner__" : t,
        channel: r.type || "",
        kind: "relationship",
        intimacy: r.intimacy || 0,
      });
    }

    const sortedIds = Array.from(involved).sort((a, b) => {
      const ra = TYPE_RANK[idToAgent[a]?.type] ?? 9;
      const rb = TYPE_RANK[idToAgent[b]?.type] ?? 9;
      return ra - rb;
    });

    const nodes = [];
    if (ownerInvolved) {
      nodes.push({
        data: { id: "__owner__", label: snap.owner_name || "Owner", kind: "owner" },
        classes: "owner",
      });
    }
    for (const aid of sortedIds) {
      const a = idToAgent[aid];
      if (!a) continue;
      nodes.push({
        data: { id: a.id, label: a.name || a.id, kind: "agent", agentType: a.type },
        classes: ("agent " + (a.type || "persona")).trim(),
      });
    }

    // collapse duplicate edges (same unordered pair) — keep strongest signal
    const byPair = {};
    for (const e of rawEdges) {
      if (e.source === e.target) continue;
      const key = [e.source, e.target].sort().join("||");
      const prev = byPair[key];
      if (!prev) {
        byPair[key] = e;
      } else {
        // prefer a channel edge with a message count; merge intimacy/label
        prev.msgCount = Math.max(prev.msgCount || 0, e.msgCount || 0);
        prev.intimacy = Math.max(prev.intimacy || 0, e.intimacy || 0);
        if (!prev.channel && e.channel) prev.channel = e.channel;
        if (e.kind === "relationship") prev.hasRel = true;
        if (e.kind === "channel") prev.hasChannel = true;
      }
    }

    const trunc = (s) => (s && s.length > 16 ? s.slice(0, 14) + "…" : s || "");
    const edges = Object.values(byPair).map((e, i) => ({
      data: {
        id: "e" + i,
        source: e.source,
        target: e.target,
        label: trunc(e.channel),
        intimacy: e.intimacy || 0,
      },
      classes: (e.intimacy || 0) >= 60 ? "strong" : "",
    }));

    return { nodes, edges };
  }

  function mountGraph(snap) {
    const container = $("cy-graph");
    if (!container || typeof cytoscape === "undefined") return;
    if (cyInstance) {
      try {
        cyInstance.destroy();
      } catch (_) {}
      cyInstance = null;
    }
    const { nodes, edges } = buildGraphElements(snap);
    const empty = $("graph-empty");
    if (nodes.length === 0) {
      container.style.display = "none";
      if (empty) empty.style.display = "flex";
      return;
    }
    container.style.display = "block";
    if (empty) empty.style.display = "none";

    const cs = getComputedStyle(document.body);
    const tok = (n, d) => (cs.getPropertyValue(n) || "").trim() || d;
    const C = {
      text: tok("--text", "#222"),
      textDim: tok("--text-dim", "#888"),
      textFaint: tok("--text-faint", "#aaa"),
      panel: tok("--panel", "#fff"),
      border: tok("--border", "#ddd"),
      accent: tok("--accent", "#2a4365"),
      mgr: tok("--mgr", "#dc2626"),
      creator: tok("--creator", "#ea580c"),
      persona: tok("--persona", "#2563eb"),
      dev: tok("--dev", "#16a34a"),
      user: tok("--user", "#db2777"),
    };

    cyInstance = cytoscape({
      container,
      elements: { nodes, edges },
      minZoom: 0.5,
      maxZoom: 2.5,
      boxSelectionEnabled: false,
      autounselectify: true,
      style: [
        {
          selector: "node",
          style: {
            shape: "ellipse",
            width: 56,
            height: 56,
            "background-color": C.panel,
            "border-width": 3,
            "border-color": C.border,
            label: "data(label)",
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 6,
            color: C.text,
            "font-size": 11.5,
            "font-weight": 600,
            "font-family": "-apple-system, sans-serif",
            "text-background-color": C.panel,
            "text-background-opacity": 0.85,
            "text-background-padding": 3,
            "text-background-shape": "roundrectangle",
          },
        },
        { selector: "node.agent.mgr", style: { "border-color": C.mgr } },
        { selector: "node.agent.creator", style: { "border-color": C.creator } },
        { selector: "node.agent.persona", style: { "border-color": C.persona } },
        { selector: "node.agent.dev", style: { "border-color": C.dev } },
        {
          selector: "node.owner",
          style: {
            "background-color": C.panel,
            "border-color": C.user,
            "font-weight": 700,
          },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            width: 1.6,
            "line-color": C.textDim,
            "line-style": "dashed",
            "line-dash-pattern": [4, 6],
            "target-arrow-shape": "none",
            opacity: 0.4,
            label: "data(label)",
            "text-opacity": 0,
            "font-size": 10,
            color: C.text,
            "text-background-color": C.panel,
            "text-background-opacity": 0.95,
            "text-background-padding": 2,
          },
        },
        {
          selector: "edge.strong",
          style: { "line-style": "solid", opacity: 0.85, width: 2.6, "line-color": C.accent },
        },
        { selector: "edge.hl", style: { "text-opacity": 1, opacity: 1, width: 3, "z-index": 999 } },
        { selector: "node.hl", style: { "border-width": 5, "z-index": 999 } },
      ],
      layout: {
        name: "concentric",
        concentric: (node) => {
          const k = node.data("kind");
          if (k === "owner") return 3;
          if (k === "agent") return 2;
          return 1;
        },
        levelWidth: () => 1,
        minNodeSpacing: 70,
        spacingFactor: 1.25,
        avoidOverlap: true,
        fit: true,
        padding: 25,
        startAngle: -Math.PI / 2,
        animate: false,
      },
    });

    // The graph container often hasn't reached full width at first paint, so the
    // initial fit can clip nodes to a corner; re-fit once it's sized and on resize
    // so the graph stays centered.
    const refit = () => { try { cyInstance.resize(); cyInstance.fit(undefined, 30); } catch (e) {} };
    requestAnimationFrame(refit);
    setTimeout(refit, 120);
    window.addEventListener("resize", refit);

    cyInstance.on("tap", "node.agent", (evt) => openAgent(evt.target.id()));
    cyInstance.on("mouseover", "node", (evt) => {
      const n = evt.target;
      n.addClass("hl");
      n.connectedEdges().addClass("hl");
    });
    cyInstance.on("mouseout", "node", (evt) => {
      const n = evt.target;
      n.removeClass("hl");
      n.connectedEdges().removeClass("hl");
    });
  }

  // ── render: agents grid ──────────────────────────────
  function renderAgents(snap) {
    const grid = $("agent-grid");
    if (!grid) return;
    const agents = (snap.agents || []).slice();
    if (!agents.length) {
      grid.innerHTML = '<div class="empty">No agents in this store yet.</div>';
      return;
    }
    grid.innerHTML = agents
      .map((a) => {
        const typeCls = a.type || "persona";
        const emotion = a.emotion
          ? `<span class="ac-emotion">${esc(a.emotion)}${
              a.intensity ? " · " + a.intensity : ""
            }</span>`
          : "";
        const model = a.model_override
          ? `<span class="ac-model">${esc(a.model_override)}</span>`
          : "";
        const last = a.last_active
          ? `<span title="${esc(fmtTime(a.last_active))}">active</span>`
          : "";
        return `<div class="agent-card ${esc(typeCls)}" data-id="${esc(a.id)}">
          <div class="ac-top">
            <span class="ac-name" title="${esc(a.name || a.id)}">${esc(a.name || a.id)}</span>
            <span class="ac-type">${esc(a.type || "agent")}</span>
          </div>
          <div class="ac-meta">${emotion}${model}${last}</div>
        </div>`;
      })
      .join("");
    grid.querySelectorAll(".agent-card").forEach((el) => {
      el.addEventListener("click", () => openAgent(el.getAttribute("data-id")));
    });
  }

  // ── render: channels ─────────────────────────────────
  function renderChannels(snap) {
    const list = $("channel-list");
    if (!list) return;
    const channels = (snap.channels || []).slice();
    channels.sort((a, b) => (b.msg_count || 0) - (a.msg_count || 0));
    if (!channels.length) {
      list.innerHTML = '<div class="empty">No channels yet.</div>';
      return;
    }
    list.innerHTML = channels
      .map((c) => {
        const n = (c.participants || []).length;
        return `<div class="channel-row" data-name="${esc(c.channel)}">
          <span class="ch-name">${esc(c.channel)}</span>
          <span class="ch-stat">${n} participant${n === 1 ? "" : "s"}</span>
          <span class="ch-stat count">${c.msg_count || 0} msg</span>
        </div>`;
      })
      .join("");
    list.querySelectorAll(".channel-row").forEach((el) => {
      el.addEventListener("click", () => openChannel(el.getAttribute("data-name")));
    });
  }

  // ── KPIs ─────────────────────────────────────────────
  function renderKpis(snap) {
    const agents = snap.agents || [];
    const channels = snap.channels || [];
    const totalMsgs = channels.reduce((s, c) => s + (c.msg_count || 0), 0);
    const set = (id, v) => {
      const el = $(id);
      if (el) el.textContent = v;
    };
    set("kpi-agents", agents.length);
    set("kpi-channels", channels.length);
    set("kpi-messages", totalMsgs);
    set("kpi-relationships", (snap.relationships || []).length);
  }

  // ── modal infra ──────────────────────────────────────
  function openModal(title, bodyHtml) {
    closeModal();
    const wrap = document.createElement("div");
    wrap.className = "modal-backdrop";
    wrap.id = "modal-backdrop";
    wrap.innerHTML = `<div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>${esc(title)}</h3>
        <button class="x" aria-label="Close">✕</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
    </div>`;
    document.body.appendChild(wrap);
    document.documentElement.classList.add("modal-open");
    document.body.classList.add("modal-open");
    wrap.addEventListener("click", (e) => {
      if (e.target === wrap) closeModal();
    });
    wrap.querySelector(".x").addEventListener("click", closeModal);
  }
  function closeModal() {
    const w = $("modal-backdrop");
    if (w) w.remove();
    document.documentElement.classList.remove("modal-open");
    document.body.classList.remove("modal-open");
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  // ── agent detail ─────────────────────────────────────
  async function openAgent(id) {
    if (!id) return;
    openModal("Loading…", '<div class="empty">Loading agent…</div>');
    const d = await fetchJson(`/api/agent_detail?id=${encodeURIComponent(id)}`);
    if (!d || d.error) {
      openModal("Error", `<div class="empty">${esc((d && d.error) || "failed to load")}</div>`);
      return;
    }

    const tags = [];
    if (d.type) tags.push(`<span class="detail-tag">${esc(d.type)}</span>`);
    if (d.emotion)
      tags.push(
        `<span class="detail-tag">${esc(d.emotion)}${
          d.intensity ? " · " + d.intensity : ""
        }</span>`
      );
    if (d.model_override)
      tags.push(`<span class="detail-tag">${esc(d.model_override)}</span>`);
    if (d.status) tags.push(`<span class="detail-tag">${esc(d.status)}</span>`);

    // relationships
    const rels = (d.relationships || []).slice();
    const relsHtml = rels.length
      ? rels
          .map((r) => {
            const pct = Math.min(100, Math.max(0, r.intimacy || 0));
            return `<div class="rel-row">
              <span class="rel-name">${esc(r.other_id)}</span>
              <span class="rel-type">${esc(r.type || "—")}</span>
              <span class="intimacy-bar"><span style="width:${pct}%"></span></span>
              <span class="intimacy-num">${r.intimacy || 0}/100</span>
            </div>`;
          })
          .join("")
      : '<div class="empty">No relationships.</div>';

    // facts
    const facts = (d.facts || []).slice();
    const factsHtml = facts.length
      ? facts
          .map(
            (f) => `<div class="fact-row">
              <span class="fact-subj">${esc(f.subject)}</span>
              <span class="fact-pred">${esc(f.predicate)}</span>
              <span class="fact-obj">${esc(f.object)}</span>
              ${f.importance ? `<span class="fact-imp">${esc(f.importance)}</span>` : ""}
            </div>`
          )
          .join("")
      : '<div class="empty">No semantic facts.</div>';

    // pinned + per-channel 5-layer memory
    const LEVEL_LABEL = { 0: "L0", 1: "L1", 2: "L2", 3: "L3", 4: "L4" };
    const memItem = (m, withPin) =>
      `<div class="mem-item">
        <span class="mem-level">${esc(LEVEL_LABEL[m.level] != null ? LEVEL_LABEL[m.level] : "L" + m.level)}</span>
        ${withPin && m.is_pinned ? '<span class="mem-pin">📌</span>' : ""}
        <span class="mem-content">${esc(m.content)}</span>
        <span class="mem-ts">${esc(fmtTime(m.created_at))}</span>
      </div>`;

    const pinned = (d.pinned_memories || []).slice();
    const pinnedHtml = pinned.length
      ? pinned.map((m) => memItem(m, false)).join("")
      : "";

    const byChannel = d.memories_by_channel || {};
    const chNames = Object.keys(byChannel);
    let memHtml = "";
    if (pinnedHtml) {
      memHtml += `<div class="mem-channel"><div class="mc-head">pinned</div>${pinnedHtml}</div>`;
    }
    for (const ch of chNames) {
      const block = byChannel[ch] || {};
      const levels = block.levels || {};
      const rows = [];
      Object.keys(levels)
        .sort((a, b) => Number(b) - Number(a))
        .forEach((lvl) => {
          for (const m of levels[lvl] || []) rows.push(memItem(m, true));
        });
      if (rows.length) {
        memHtml += `<div class="mem-channel"><div class="mc-head">${esc(ch)}</div>${rows.join(
          ""
        )}</div>`;
      }
    }
    if (!memHtml) memHtml = '<div class="empty">No memory recorded.</div>';

    const body = `
      <div>${tags.join("")}</div>
      <div class="section"><h4>Relationships</h4>${relsHtml}</div>
      <div class="section"><h4>Semantic facts</h4>${factsHtml}</div>
      <div class="section"><h4>Memory (5-layer)</h4>${memHtml}</div>`;
    openModal(d.name || d.id, body);
  }

  // ── channel viewer ───────────────────────────────────
  async function openChannel(name) {
    if (!name) return;
    openModal("Loading…", '<div class="empty">Loading channel…</div>');
    const d = await fetchJson(`/api/channel?name=${encodeURIComponent(name)}`);
    if (!d || d.error) {
      openModal("Error", `<div class="empty">${esc((d && d.error) || "failed to load")}</div>`);
      return;
    }
    const ownerIds = new Set((window.__GLIMI_SNAP__ || {}).owner_ids || []);
    const agentIds = new Set(((window.__GLIMI_SNAP__ || {}).agents || []).map((a) => a.id));
    const parts = (d.participants || [])
      .map((p) => `<span class="detail-tag">${esc(p)}</span>`)
      .join("");
    const msgs = (d.messages || []).slice();
    const msgsHtml = msgs.length
      ? msgs
          .map((m) => {
            const sid = m.speaker || m.speaker_id || "";
            const isOwner = ownerIds.has(sid) || (!agentIds.has(sid) && m.is_user);
            return `<div class="chat-msg">
              <span class="who ${isOwner ? "is-owner" : ""}">${esc(sid)}</span>
              <span class="text">${esc(m.message)}</span>
              <span class="when">${esc(fmtTime(m.timestamp))}</span>
            </div>`;
          })
          .join("")
      : '<div class="empty">No messages.</div>';
    const body = `
      <div class="section"><h4>Participants</h4>${parts || '<span class="empty">none</span>'}</div>
      <div class="section"><h4>Messages (${msgs.length})</h4>${msgsHtml}</div>`;
    openModal("#" + name, body);
  }

  // ── LLM usage ────────────────────────────────────────
  // $ is only meaningful when there is real (SDK/API-key) spend. When every
  // counted call is estimated (CLI subscription path) or all are local ($0),
  // we surface tokens + latency instead of a misleading dollar figure.
  function fmtUsd(v) {
    const n = Number(v) || 0;
    if (n <= 0) return "$0.00";
    if (n < 0.01) return "<$0.01";
    return "$" + n.toFixed(2);
  }
  function renderUsage(u) {
    const set = (id, v) => {
      const el = $(id);
      if (el) el.textContent = v;
    };
    if (!u || u.call_count_month == null) {
      set("usage-today", "—"); set("usage-month", "—");
      set("usage-calls", "—"); set("usage-latency", "—");
      return;
    }
    const callsMonth = u.call_count_month || 0;
    const estMonth = u.estimated_count_month || 0;
    const allEstimated = callsMonth > 0 && estMonth >= callsMonth;
    const hasDollars = (u.spend_month || 0) > 0 || (u.spend_today || 0) > 0;

    // Spend cards: show $ only when there is real (non-estimated) priced spend.
    if (hasDollars && !allEstimated) {
      set("usage-today", fmtUsd(u.spend_today));
      set("usage-month", fmtUsd(u.spend_month));
    } else if (hasDollars && allEstimated) {
      set("usage-today", fmtUsd(u.spend_today) + " est.");
      set("usage-month", fmtUsd(u.spend_month) + " est.");
    } else {
      // No priced spend (local / CLI no-key) — show tokens instead of $0.
      const tk = (u.input_tokens_month || 0) + (u.output_tokens_month || 0);
      set("usage-today", "—");
      set("usage-month", tk.toLocaleString() + " tok");
    }
    set("usage-calls", callsMonth.toLocaleString());
    set("usage-latency", (u.avg_latency_ms || 0).toLocaleString() + " ms");

    const note = $("usage-note");
    if (note) {
      const bits = ["month-to-date"];
      if (estMonth > 0) bits.push(estMonth + " est. (CLI)");
      if (u.pricing_as_of) bits.push("prices " + u.pricing_as_of);
      note.textContent = bits.join(" · ");
    }
  }

  // ── tool-call timeline ───────────────────────────────
  function renderTimeline(rows) {
    const list = $("tool-timeline");
    if (!list) return;
    rows = rows || [];
    if (!rows.length) {
      list.innerHTML = '<div class="empty">No tool calls recorded yet.</div>';
      return;
    }
    list.innerHTML = rows
      .map((r) => {
        const ok = Number(r.ok) === 1;
        const mark = ok ? "✓" : "✗";
        const cls = ok ? "tc-ok" : "tc-err";
        const args = r.args_json ? String(r.args_json) : "";
        const argsShort = args.length > 80 ? args.slice(0, 80) + "…" : args;
        const prev = r.result_preview ? String(r.result_preview) : "";
        const lat = r.latency_ms != null ? r.latency_ms + " ms" : "";
        return `<div class="tool-row ${cls}">
          <span class="tc-mark">${mark}</span>
          <span class="tc-name">${esc(r.tool_name)}</span>
          <span class="tc-args" title="${esc(args)}">${esc(argsShort)}</span>
          <span class="tc-prev" title="${esc(prev)}">${esc(prev)}</span>
          <span class="tc-lat">${esc(lat)}</span>
          <span class="tc-time" title="${esc(fmtTime(r.created_at))}">${esc(r.agent_id || "")}</span>
        </div>`;
      })
      .join("");
  }

  // ── boot ─────────────────────────────────────────────
  async function load() {
    const snap = await fetchJson("/api/snapshot");
    if (!snap) {
      const err = $("load-error");
      if (err) err.style.display = "block";
      return;
    }
    window.__GLIMI_SNAP__ = snap;
    renderKpis(snap);
    renderAgents(snap);
    renderChannels(snap);
    mountGraph(snap);
    // Observability panels — store-backed, best-effort (degrade to empty).
    renderUsage(await fetchJson("/api/usage"));
    renderTimeline(await fetchJson("/api/tool_timeline"));
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    load();
  });
})();
