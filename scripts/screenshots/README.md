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

PNGs are written to `docs/screenshots/en/`. Re-run anytime; output is
deterministic (same regions, same waits, retina `deviceScaleFactor:2`).

## How it works

- `capture.mjs` — launches headless Chrome, loops over the **`SHOTS` array**
  (the single source of truth — edit it to add/retune shots), navigates to each
  URL, waits for `networkidle2` + a fixed settle, then screenshots.
- Dark shots force dark two ways: the `prefers-color-scheme` media feature **and**
  the app's own `localStorage['glimi-theme']='dark'` (set before first paint).
- Mobile shots use 390x844 with `isMobile`/touch.
- The connection-graph shot opens the community **Overview** tab, lets cytoscape
  fit/center, then element-clips the graph card → a crisp **static** PNG
  (`04-graph-live.png`, replacing the old animated webp).

While capturing it also reports, per URL, any browser **console errors** and
**failed requests** — a built-in live-demo health check.

## Config

- Chrome path defaults to
  `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.
  Override with `CHROME_PATH=/path/to/chrome node capture.mjs`.
- Add a shot: append `{ name, url, ... }` to `SHOTS`. See the comment block at
  the top of `capture.mjs` for every supported key (`element`, `clip`,
  `fullPage`, `dark`, `mobile`, `prep`, `waitFor`, `settle`).
