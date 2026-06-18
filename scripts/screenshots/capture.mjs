// ---------------------------------------------------------------------------
// Glimi — reproducible README screenshot capture
// ---------------------------------------------------------------------------
// Drives the installed Google Chrome (no chromium download) via puppeteer-core
// and re-captures the README demo screenshots from the LIVE public demos, which
// are the source of truth for the current UI.
//
//   cd scripts/screenshots && npm i && node capture.mjs
//
// Determinism contract — same regions, same way, every run:
//   • headless 'new', deviceScaleFactor 2 (retina-crisp PNGs)
//   • each shot waits for networkidle2 + a fixed settle (SETTLE_MS, longer where
//     a shot opts in via `settle`), so async UI (chat feed, cytoscape) is painted
//   • dark mode is forced two ways (prefers-color-scheme media + localStorage
//     'glimi-theme', the app's own toggle key — see templates/base.html)
//   • the SHOTS array below is the SINGLE SOURCE OF TRUTH. Edit it to add/retune
//     shots; everything else is plumbing.
//
// Per-shot config keys:
//   name      output filename stem  → docs/screenshots/en/<name>.png   (required)
//   url       page to navigate to                                       (required)
//   width/height   viewport in CSS px (defaults 1440x900)
//   dark      true → force dark theme before first paint
//   mobile    true → 390x844, isMobile, touch (overrides width/height)
//   settle    extra settle ms for this shot (added on top of SETTLE_MS)
//   waitFor   CSS selector to await before capturing (e.g. '.feed .msg')
//   prep      async (page) => {}  run after load+settle, before capture
//             (click a tab, fit a graph, dismiss chrome, etc.)
//   element   CSS selector → clip to that element's box (crisp element shot)
//   clip      {x,y,width,height} → clip to an explicit rectangle
//   fullPage  true → full scrollable page (else viewport-only, the default)
//   skip      true (+ note) → logged as skipped, not captured
// ---------------------------------------------------------------------------

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Installed Chrome on macOS (no bundled chromium — puppeteer-core needs this).
const CHROME =
  process.env.CHROME_PATH ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

// PNGs land here. README references docs/screenshots/en/<name>.png.
const OUT_DIR = path.resolve(__dirname, '../../docs/screenshots/en');

const DEFAULT_W = 1440;
const DEFAULT_H = 900;
const SETTLE_MS = 1500; // baseline settle after networkidle2, every shot

// Live demo hosts (source of truth — current UI, no auth needed). Each is
// env-overridable so the same script can target a local server for a one-off
// regenerate (e.g. GLIMI_COMMUNITY_HOST=http://127.0.0.1:8911) without editing.
const LANDING = process.env.GLIMI_LANDING_HOST || 'https://glimi.iruyo.com';
const COMMUNITY = process.env.GLIMI_COMMUNITY_HOST || 'https://glimi-community.iruyo.com';
const WORKSPACE = process.env.GLIMI_WORKSPACE_HOST || 'https://glimi-workspace.iruyo.com';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- shared prep helpers ---------------------------------------------------

// Wait for the chat feed to have at least one rendered message bubble.
const waitChat = async (page) => {
  await page
    .waitForSelector('.feed .msg', { timeout: 20000 })
    .catch(() => {}); // best-effort: still capture if the feed stays empty
  await sleep(600); // let the last bubbles/avatars settle
};

// Community dashboard: click a top-nav tab by its data-tab value, then settle.
const openTab = (tab, settle = 1200) => async (page) => {
  await page.waitForSelector(`nav.tabs button[data-tab="${tab}"]`, {
    timeout: 15000,
  });
  await page.click(`nav.tabs button[data-tab="${tab}"]`);
  await sleep(settle);
};

// Community dashboard: switch to the Overview tab and let cytoscape fit/center.
const openOverviewGraph = async (page) => {
  await page.waitForSelector('nav.tabs button[data-tab="overview"]', {
    timeout: 15000,
  });
  await page.click('nav.tabs button[data-tab="overview"]');
  // graph renders on tab activation; give cytoscape time to lay out + fit.
  await sleep(2000);
  // explicitly re-fit if the helper is present (idempotent, centers the graph).
  await page.evaluate(() => {
    if (typeof window.cyFitGraph === 'function') window.cyFitGraph();
  });
  await sleep(1200);
};

// --- the single source of truth -------------------------------------------

const SHOTS = [
  // === community connection graph =========================================
  // 04 (04-graph-live.webp) is an ANIMATED clip, not a still — it's produced by
  // captureAnimatedGraph() after this SHOTS loop (it drives the ?graphdemo live
  // choreography and encodes frames → webp). It is intentionally NOT in SHOTS.
  //
  // 05: same graph, maximized fullscreen via the graph's own maximize button.
  {
    name: '05-connection-graph',
    url: `${COMMUNITY}/community/demo`,
    prep: async (page) => {
      await openOverviewGraph(page);
      // toggleGraphFullscreen() adds body.graph-fullscreen + re-fits with padding.
      await page.evaluate(() => {
        if (typeof window.toggleGraphFullscreen === 'function')
          window.toggleGraphFullscreen();
      });
      await sleep(1800);
      await page.evaluate(() => {
        if (typeof window.cyFitGraph === 'function') window.cyFitGraph();
      });
      await sleep(800);
    },
    element: '#graph-panel',
  },

  // === community web chat ====================================================
  // 08: light desktop chat, clipped to the main chat surface.
  {
    name: '08-web-chat',
    url: `${COMMUNITY}/community/demo`,
    waitFor: '.feed .msg',
    prep: waitChat,
    element: '#chat-shell',
  },
  // 09: same, dark.
  {
    name: '09-web-chat-dark',
    url: `${COMMUNITY}/community/demo`,
    dark: true,
    waitFor: '.feed .msg',
    prep: waitChat,
    element: '#chat-shell',
  },
  // 10: mobile chat (sidebar collapses to a drawer at narrow widths).
  {
    name: '10-web-chat-mobile',
    url: `${COMMUNITY}/community/demo`,
    mobile: true,
    waitFor: '.feed .msg',
    prep: waitChat,
  },
  // 11: full community window (whole dashboard chrome + chat), light.
  {
    name: '11-community-dashboard',
    url: `${COMMUNITY}/community/demo`,
    waitFor: '.feed .msg',
    prep: waitChat,
  },
  // 16: community chat showing the read-only demo banner — frame the composer
  //     area so the banner is in shot. Element-clip the main chat section.
  {
    name: '16-community-demo-readonly',
    url: `${COMMUNITY}/community/demo`,
    waitFor: '.feed .msg',
    prep: async (page) => {
      await waitChat(page);
      // The read-only banner lives just above the composer; make sure it's
      // un-hidden (chat.js toggles it for read-only communities).
      await page
        .waitForSelector('#chat-readonly-banner:not([hidden])', {
          timeout: 6000,
        })
        .catch(() => {});
    },
    element: 'section.main',
  },

  // === workspace =============================================================
  // 13: workspace community-style chat.
  {
    name: '13-workspace-full',
    url: `${WORKSPACE}/w/demo`,
    waitFor: '.feed .msg',
    prep: waitChat,
  },
  // 15: workspace home.
  {
    name: '15-workspace-home',
    url: `${WORKSPACE}/`,
    settle: 800,
  },

  // === landing (language picker) ============================================
  // 17: KO landing.
  { name: '17-landing', url: `${LANDING}/`, settle: 600 },
  // 18: EN landing.
  { name: '18-landing-en', url: `${LANDING}/?lang=en`, settle: 600 },

  // === best-effort: dashboard tabs + agent detail ===========================
  // 01: community Overview tab — full window (KPIs, graph, agents, recents).
  {
    name: '01-dashboard',
    url: `${COMMUNITY}/community/demo`,
    prep: openOverviewGraph, // also lands on Overview + fits the graph
  },
  // 02: persona memory — agent detail full page (5-layer memory, relationships).
  {
    name: '02-persona-memory',
    url: `${COMMUNITY}/agent/agent-persona-001?community=demo`,
    waitFor: '#profile',
    settle: 1200,
  },
  // 06: connection graph WITH supervisors shown — element-clip of the graph card.
  //     glimi-show-supervisors is read at module init, so seed it pre-load.
  {
    name: '06-graph-supervisor',
    url: `${COMMUNITY}/community/demo`,
    localStorage: { 'glimi-show-supervisors': 'true' },
    settle: 800,
    prep: openOverviewGraph,
    element: '#graph-panel',
  },
  // 07: Channels tab — DM + group + internal channels list.
  {
    name: '07-dm-channels',
    url: `${COMMUNITY}/community/demo`,
    prep: openTab('channels', 1500),
  },

  // === skipped (no clean reproducible path) =================================
  // 03: Achievements — the achievements API is 401 for anonymous demo viewers,
  //     so the tab renders empty/locked without login. Needs an authed session.
  {
    name: '03-achievements',
    skip: true,
    note: 'achievements API is 401 for anon demo viewers — needs authed session',
  },
  // 14: workspace agent detail — workspace has no standalone /agent route (404);
  //     detail is an in-chat modal (click an avatar). Not reliably driveable
  //     headless without brittle DOM coordinates.
  {
    name: '14-workspace-agent-detail',
    skip: true,
    note: 'no standalone agent-detail route on workspace (modal-only); kept existing PNG',
  },
];

// --- console / network health collection -----------------------------------
// Doubles as a live-demo health check: per-URL console errors + failed requests.
function attachHealth(page, sink) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') sink.consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => {
    sink.consoleErrors.push(`[pageerror] ${err.message}`);
  });
  page.on('requestfailed', (req) => {
    const f = req.failure();
    sink.requestFailures.push(
      `${req.url()} — ${f ? f.errorText : 'failed'}`
    );
  });
}

// --- capture one shot ------------------------------------------------------
async function capture(browser, shot) {
  const page = await browser.newPage();
  const health = { consoleErrors: [], requestFailures: [] };
  attachHealth(page, health);

  const isMobile = !!shot.mobile;
  const width = isMobile ? 390 : shot.width || DEFAULT_W;
  const height = isMobile ? 844 : shot.height || DEFAULT_H;

  await page.setViewport({
    width,
    height,
    deviceScaleFactor: 2, // retina-crisp
    isMobile,
    hasTouch: isMobile,
  });

  // Theme: force the intended theme for EVERY shot, both ways — the media
  // feature AND the app's own toggle key (localStorage 'glimi-theme', read
  // before first paint in templates/base.html). This is explicit on purpose:
  // pages on the same origin share storage across shots, so a prior dark shot
  // would otherwise bleed 'glimi-theme=dark' into a later light shot. Setting
  // both ends every time makes output independent of shot order (determinism).
  const theme = shot.dark ? 'dark' : 'light';
  await page.emulateMediaFeatures([
    { name: 'prefers-color-scheme', value: theme },
  ]);
  // Seed app prefs into localStorage before first paint. These are read at
  // module init, so they must be present before the page's JS runs. Defaults
  // are ALWAYS set explicitly (theme, supervisor toggle off) so a prior shot's
  // value can't leak across the shared same-origin storage; a shot then
  // overrides via shot.localStorage (e.g. turn supervisors on for 06).
  const prefs = {
    'glimi-theme': theme,
    'glimi-show-supervisors': 'false',
    ...(shot.localStorage || {}),
  };
  await page.evaluateOnNewDocument((p) => {
    try {
      for (const [k, v] of Object.entries(p)) localStorage.setItem(k, v);
    } catch (e) {}
  }, prefs);

  await page.goto(shot.url, { waitUntil: 'networkidle2', timeout: 60000 });

  // Belt-and-suspenders: also set the attribute live (in case the page was
  // already partway rendered before the init script took effect).
  await page.evaluate((t) => {
    document.documentElement.setAttribute('data-theme', t);
  }, theme);

  await sleep(SETTLE_MS + (shot.settle || 0));

  if (shot.waitFor) {
    await page
      .waitForSelector(shot.waitFor, { timeout: 20000 })
      .catch(() => {});
  }
  if (shot.prep) await shot.prep(page);

  const outPath = path.join(OUT_DIR, `${shot.name}.png`);
  const opts = { path: outPath, type: 'png' };

  if (shot.element) {
    const el = await page.$(shot.element);
    if (!el) throw new Error(`element not found: ${shot.element}`);
    await el.screenshot(opts);
  } else if (shot.clip) {
    await page.screenshot({ ...opts, clip: shot.clip });
  } else if (shot.fullPage) {
    await page.screenshot({ ...opts, fullPage: true });
  } else {
    await page.screenshot(opts); // viewport
  }

  await page.close();
  return { outPath, health, width, height };
}

// --- animated connection-graph clip ----------------------------------------
// 04-graph-live.webp — a LOOPING animated WebP of the connection graph alive:
// several nodes haloing (thinking/speaking) and several edges streaming at once.
// The public demo seed is static, so we drive the in-app showcase choreography
// (?graphdemo → window.startGraphDemo()) and record the canvas over time, then
// encode the frames to an animated WebP with libwebp's img2webp.
//
// Why a script-driven clip and not a screen recording: same region, same motion,
// same length every run — reproducible, like every other shot here.
const GRAPH_WEBP = {
  url: `${COMMUNITY}/community/demo?graphdemo`,
  width: 1200,
  height: 720,
  scale: 2, // retina-crisp; README displays it small so size stays modest
  frames: 44, // ~ a couple of full wave cycles (beat = 640ms)
  interval: 55, // ms between frame grabs (grab is itself ~80–150ms headless)
  quality: 66, // img2webp lossy quality (graph = flat colours → compresses well)
};
async function captureAnimatedGraph(browser) {
  const page = await browser.newPage();
  const health = { consoleErrors: [], requestFailures: [] };
  attachHealth(page, health);

  await page.setViewport({
    width: GRAPH_WEBP.width,
    height: GRAPH_WEBP.height,
    deviceScaleFactor: GRAPH_WEBP.scale,
  });
  // Force light theme both ways (see capture() for the rationale).
  await page.emulateMediaFeatures([
    { name: 'prefers-color-scheme', value: 'light' },
  ]);
  await page.evaluateOnNewDocument((p) => {
    try {
      for (const [k, v] of Object.entries(p)) localStorage.setItem(k, v);
    } catch (e) {}
  }, { 'glimi-theme': 'light', 'glimi-show-supervisors': 'false' });

  await page.goto(GRAPH_WEBP.url, { waitUntil: 'networkidle2', timeout: 60000 });
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
  await sleep(SETTLE_MS);

  // Land on Overview, fit/center the graph, then let avatars (node background
  // images, loaded async by cytoscape) settle before we start recording.
  await openOverviewGraph(page);
  await sleep(2500);
  await page.evaluate(() => {
    if (typeof window.cyFitGraph === 'function') window.cyFitGraph();
    if (typeof window.startGraphDemo === 'function') window.startGraphDemo();
  });
  await sleep(1200); // first beats run + last avatars paint

  const el = await page.$('#graph-panel');
  if (!el) throw new Error('graph panel not found (#graph-panel)');

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glimi-graph-'));
  const frameFiles = [];
  const t0 = Date.now();
  for (let i = 0; i < GRAPH_WEBP.frames; i++) {
    const f = path.join(tmp, `f${String(i).padStart(3, '0')}.png`);
    await el.screenshot({ path: f, type: 'png' });
    frameFiles.push(f);
    await sleep(GRAPH_WEBP.interval);
  }
  const elapsed = Date.now() - t0;
  await page.close();

  // Per-frame duration = real elapsed / frames → playback matches capture speed.
  const d = Math.max(50, Math.round(elapsed / GRAPH_WEBP.frames));
  const out = path.join(OUT_DIR, '04-graph-live.webp');
  // frame options (-lossy -q -m -d) persist for all subsequent input frames.
  const args = [
    '-loop', '0',
    '-lossy', '-q', String(GRAPH_WEBP.quality), '-m', '6', '-d', String(d),
    ...frameFiles,
    '-o', out,
  ];
  execFileSync('img2webp', args, { stdio: ['ignore', 'ignore', 'inherit'] });

  for (const f of frameFiles) { try { fs.unlinkSync(f); } catch (e) {} }
  try { fs.rmdirSync(tmp); } catch (e) {}

  const { size } = fs.statSync(out);
  return { outPath: out, bytes: size, frames: GRAPH_WEBP.frames, frameMs: d, health };
}

// --- run all ---------------------------------------------------------------
async function main() {
  if (!fs.existsSync(CHROME)) {
    console.error(`Chrome not found at: ${CHROME}\nSet CHROME_PATH to override.`);
    process.exit(1);
  }
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-color-profile=srgb'],
  });

  const results = [];
  const healthByUrl = {}; // url → {consoleErrors:Set, requestFailures:Set}

  // ONLY_GRAPH_WEBP=1 → skip the still SHOTS, regenerate just 04-graph-live.webp.
  const onlyGraph = !!process.env.ONLY_GRAPH_WEBP;
  for (const shot of (onlyGraph ? [] : SHOTS)) {
    if (shot.skip) {
      console.log(`SKIP  ${shot.name}  — ${shot.note || 'skipped'}`);
      results.push({ name: shot.name, skipped: true, note: shot.note });
      continue;
    }
    process.stdout.write(`shoot ${shot.name} … `);
    try {
      const { outPath, health, width, height } = await capture(browser, shot);
      const { size } = fs.statSync(outPath);
      console.log(`ok  ${width}x${height}  ${(size / 1024).toFixed(0)} KB`);
      results.push({ name: shot.name, path: outPath, bytes: size });

      // fold health into a per-URL bucket (dedup across repeated URLs)
      const bucket = (healthByUrl[shot.url] ||= {
        consoleErrors: new Set(),
        requestFailures: new Set(),
      });
      health.consoleErrors.forEach((e) => bucket.consoleErrors.add(e));
      health.requestFailures.forEach((e) => bucket.requestFailures.add(e));
    } catch (err) {
      console.log(`FAIL  ${err.message}`);
      results.push({ name: shot.name, error: err.message });
    }
  }

  // --- animated connection-graph clip (04-graph-live.webp) ----------------
  if (!process.env.SKIP_GRAPH_WEBP) {
    process.stdout.write('clip  04-graph-live.webp … ');
    try {
      const { outPath, bytes, frames, frameMs, health } =
        await captureAnimatedGraph(browser);
      console.log(
        `ok  ${frames} frames @ ${frameMs}ms  ${(bytes / 1024).toFixed(0)} KB`
      );
      results.push({ name: '04-graph-live', path: outPath, bytes });
      const bucket = (healthByUrl[GRAPH_WEBP.url] ||= {
        consoleErrors: new Set(),
        requestFailures: new Set(),
      });
      health.consoleErrors.forEach((e) => bucket.consoleErrors.add(e));
      health.requestFailures.forEach((e) => bucket.requestFailures.add(e));
    } catch (err) {
      console.log(`FAIL  ${err.message}`);
      results.push({ name: '04-graph-live', error: err.message });
    }
  }

  await browser.close();

  // --- summary -------------------------------------------------------------
  console.log('\n===== FILES =====');
  for (const r of results) {
    if (r.skipped) console.log(`  skipped  ${r.name}  (${r.note || ''})`);
    else if (r.error) console.log(`  FAILED   ${r.name}  — ${r.error}`);
    else
      console.log(
        `  ${path.basename(r.path).padEnd(30)} ${(r.bytes / 1024)
          .toFixed(0)
          .padStart(5)} KB`
      );
  }

  console.log('\n===== LIVE-DEMO HEALTH (per URL) =====');
  for (const [url, h] of Object.entries(healthByUrl)) {
    const errs = [...h.consoleErrors];
    const fails = [...h.requestFailures];
    if (!errs.length && !fails.length) {
      console.log(`  ${url}\n    clean (no console errors, no failed requests)`);
      continue;
    }
    console.log(`  ${url}`);
    if (errs.length) {
      console.log(`    console errors (${errs.length}):`);
      errs.forEach((e) => console.log(`      - ${e}`));
    }
    if (fails.length) {
      console.log(`    failed requests (${fails.length}):`);
      fails.forEach((e) => console.log(`      - ${e}`));
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
