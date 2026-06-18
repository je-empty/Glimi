# Glimi screenshot tool

Reproducible README demo screenshots. Drives the **installed Google Chrome**
(no chromium download) via `puppeteer-core`, capturing the **live public demos**
which are the source of truth for the current UI — no auth, no local server.

## Run

```bash
cd scripts/screenshots
npm i
node capture.mjs
```

PNGs (and one animated WebP) are written to `docs/screenshots/en/` — the single
canonical screenshot dir (README.md, README.ko.md and the root `index.html` all
reference it). Re-run anytime; output is deterministic (same regions, same waits,
retina `deviceScaleFactor:2`).

Regenerate **just** the animated graph clip without re-shooting the stills:

```bash
ONLY_GRAPH_WEBP=1 node capture.mjs
# or against a local server instead of the live demo:
ONLY_GRAPH_WEBP=1 GLIMI_COMMUNITY_HOST=http://127.0.0.1:8911 node capture.mjs
```

## How it works

- `capture.mjs` — launches headless Chrome, loops over the **`SHOTS` array**
  (the single source of truth — edit it to add/retune shots), navigates to each
  URL, waits for `networkidle2` + a fixed settle, then screenshots.
- Dark shots force dark two ways: the `prefers-color-scheme` media feature **and**
  the app's own `localStorage['glimi-theme']='dark'` (set before first paint).
- Mobile shots use 390x844 with `isMobile`/touch.
- **`04-graph-live.webp`** is an *animated* clip, not a still. After the `SHOTS`
  loop, `captureAnimatedGraph()` opens the community **Overview**, drives the
  in-app showcase choreography (`?graphdemo` → `window.startGraphDemo()`, which
  flows a wave of thinking/speaking activity across the graph so it looks alive),
  records the canvas frame-by-frame, and encodes them to a looping WebP with
  libwebp's `img2webp`. Set `SKIP_GRAPH_WEBP=1` to skip it.
- The other graph stills (`05-connection-graph`, `06-graph-supervisor`) are
  normal element-clipped PNGs from the `SHOTS` array.

While capturing it also reports, per URL, any browser **console errors** and
**failed requests** — a built-in live-demo health check.

## Config

- Chrome path defaults to
  `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.
  Override with `CHROME_PATH=/path/to/chrome node capture.mjs`.
- Add a shot: append `{ name, url, ... }` to `SHOTS`. See the comment block at
  the top of `capture.mjs` for every supported key (`element`, `clip`,
  `fullPage`, `dark`, `mobile`, `prep`, `waitFor`, `settle`).
