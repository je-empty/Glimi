# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""EDD report rendering — a generation → a self-contained HTML report → PDF.

Domain-neutral: it renders any generation record (see
:meth:`glimi.edd.GenerationStore.record`) into a print-optimized, fully self-contained
HTML one-pager (inline CSS, server-rendered SVG trend — no JS needed so it prints
identically), and optionally to PDF via Playwright's headless Chromium.

Playwright is an OPTIONAL dependency: importing this module never requires it; only
:func:`html_to_pdf` imports it (lazily) and raises a clear error if it's absent.
"""
from __future__ import annotations

import html as _html
from pathlib import Path
from typing import Optional


def _esc(v) -> str:
    return _html.escape("" if v is None else str(v))


def _trend_svg(trend: list[dict], *, w: int = 720, h: int = 200, gate: int = 70) -> str:
    """Server-rendered SVG line of overall_score across generations (no JS)."""
    pts = [(g.get("generation_no"), g.get("overall_score"), g.get("passed"))
           for g in trend if g.get("overall_score") is not None]
    if not pts:
        return ""
    padL, padR, padT, padB = 34, 14, 16, 22
    n = len(pts)
    x_at = lambda i: padL + ((w - padL - padR) / 2 if n == 1
                             else (w - padL - padR) * i / (n - 1))
    y_at = lambda v: padT + (h - padT - padB) * (1 - v / 100.0)
    s = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">']
    for v in (0, 50, 100):
        y = y_at(v)
        s.append(f'<line x1="{padL}" y1="{y:.1f}" x2="{w-padR}" y2="{y:.1f}" '
                 f'stroke="#e7e2d8" stroke-width="1"/>')
        s.append(f'<text x="{padL-6}" y="{y+3:.1f}" text-anchor="end" font-size="10" '
                 f'fill="#9a9388">{v}</text>')
    gy = y_at(gate)
    s.append(f'<line x1="{padL}" y1="{gy:.1f}" x2="{w-padR}" y2="{gy:.1f}" stroke="#b76e0e" '
             f'stroke-width="1" stroke-dasharray="4 4" opacity="0.6"/>')
    s.append(f'<text x="{w-padR}" y="{gy-4:.1f}" text-anchor="end" font-size="10" '
             f'fill="#b76e0e">gate {gate}</text>')
    path = " ".join(f'{"L" if i else "M"}{x_at(i):.1f},{y_at(v):.1f}'
                    for i, (_, v, _) in enumerate(pts))
    s.append(f'<path d="{path}" fill="none" stroke="#3f5d80" stroke-width="2.5" '
             f'stroke-linejoin="round"/>')
    for i, (no, v, passed) in enumerate(pts):
        c = "#1f9d57" if passed else "#c0392b"
        s.append(f'<circle cx="{x_at(i):.1f}" cy="{y_at(v):.1f}" r="4" fill="{c}"/>')
        s.append(f'<text x="{x_at(i):.1f}" y="{y_at(v)-9:.1f}" text-anchor="middle" '
                 f'font-size="10" fill="#9a9388">{v}</text>')
    s.append("</svg>")
    return "".join(s)


def _dim_rows(dimensions: list[dict]) -> str:
    rows = []
    for d in dimensions:
        skipped = d.get("skipped")
        score = "skip" if skipped else f'{d.get("score")}/10'
        if skipped:
            mark, color = "—", "#9a9388"
        elif d.get("passed"):
            mark, color = "✓", "#1f9d57"
        else:
            mark, color = "✗", "#c0392b"
        bar = 0 if skipped or d.get("score") is None else min(100, float(d["score"]) * 10)
        rows.append(
            f'<tr><td style="font-weight:600">{_esc(d.get("label"))}</td>'
            f'<td style="color:{color};font-weight:700;text-align:center">{mark}</td>'
            f'<td style="text-align:right;font-variant-numeric:tabular-nums">{_esc(score)}</td>'
            f'<td style="width:30%"><div style="height:7px;background:#eee;border-radius:4px">'
            f'<div style="height:100%;width:{bar:.0f}%;background:{color};border-radius:4px"></div>'
            f'</div></td>'
            f'<td style="color:#6b655c;font-size:11px">{_esc(d.get("detail"))}</td></tr>')
    return "".join(rows)


def generation_to_html(generation: dict, *, trend: Optional[list[dict]] = None,
                       app_name: str = "Glimi") -> str:
    """Render one generation record into a self-contained, print-optimized HTML page."""
    g = generation
    git = g.get("git") or {}
    sha = f'{git.get("sha", "?")}{"*" if git.get("dirty") else ""}'
    passed = g.get("passed")
    badge_c = "#1f9d57" if passed else "#c0392b"
    badge_t = "PASS" if passed else "FAIL"
    overall = g.get("overall_score")
    overall_s = "–" if overall is None else str(overall)
    failing = ", ".join(g.get("failing") or []) or "—"
    trend_block = _trend_svg(trend) if trend else ""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Pretendard", "Apple SD Gothic Neo", system-ui, sans-serif;
          color: #2a2620; margin: 0; font-size: 13px; line-height: 1.5; }}
  h1 {{ font-size: 21px; margin: 0 0 2px; }}
  .sub {{ color: #6b655c; font-size: 12px; margin: 0 0 18px; }}
  .hero {{ display: flex; gap: 26px; align-items: center; border: 1px solid #e7e2d8;
           border-radius: 12px; padding: 18px 22px; margin-bottom: 18px; }}
  .score {{ font-size: 50px; font-weight: 800; letter-spacing: -1px; line-height: 1; }}
  .score small {{ font-size: 12px; font-weight: 400; color: #9a9388; }}
  .badge {{ display: inline-block; font-size: 11px; font-weight: 700; padding: 3px 11px;
            border-radius: 999px; color: #fff; background: {badge_c}; }}
  .meta {{ font-size: 12px; color: #6b655c; }}
  .meta b {{ color: #2a2620; }}
  .card {{ border: 1px solid #e7e2d8; border-radius: 12px; padding: 14px 18px; margin-bottom: 16px; }}
  .card h2 {{ font-size: 14px; margin: 0 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  td {{ padding: 7px 8px; border-bottom: 1px solid #f0ece3; vertical-align: middle; }}
  .foot {{ color: #9a9388; font-size: 10.5px; margin-top: 18px; }}
</style></head><body>
  <h1>{_esc(app_name)} · QA generation #{_esc(g.get("generation_no"))}</h1>
  <p class="sub">eval-driven development — autonomous owner agent run, scored across weighted dimensions.</p>

  <div class="hero">
    <div>
      <div class="score">{_esc(overall_s)}<small> / 100</small></div>
      <div style="margin-top:8px"><span class="badge">{badge_t}</span>
        <span style="color:#9a9388;font-size:11px"> · gate {_esc(g.get("min_overall") or 70)}</span></div>
    </div>
    <div class="meta">
      <div>git <b>{_esc(sha)}</b> &nbsp; branch <b>{_esc(git.get("branch"))}</b></div>
      <div>backend <b>{_esc(g.get("backend"))}</b> &nbsp; goal: {_esc(g.get("goal"))}</div>
      <div>{_esc((g.get("generated_at") or "")[:19].replace("T", " "))} UTC</div>
      <div>failing: <b style="color:{badge_c}">{_esc(failing)}</b></div>
    </div>
  </div>

  {f'<div class="card"><h2>Quality over generations</h2>{trend_block}</div>' if trend_block else ''}

  <div class="card">
    <h2>Dimensions</h2>
    <table><tbody>{_dim_rows(g.get("dimensions") or [])}</tbody></table>
  </div>

  <div class="foot">Generated by glimi.edd · run {_esc(g.get("run_id"))} · see docs/qa_system.md</div>
</body></html>"""


def html_to_pdf(html_str: str, out_path: Path | str) -> str:
    """Render an HTML string → PDF via Playwright headless Chromium (lazy import).

    Raises ``RuntimeError`` with install guidance if Playwright (or its browser) is
    not available — it is an optional dependency, not required to import this module."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "PDF export needs Playwright: `pip install playwright && playwright install chromium`"
        ) from e
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_str, wait_until="load")
            page.pdf(path=str(out_path), format="A4", print_background=True)
        finally:
            browser.close()
    return str(out_path)


def generation_to_pdf(generation: dict, out_path: Path | str, *,
                      trend: Optional[list[dict]] = None, app_name: str = "Glimi") -> str:
    """Render one generation record straight to a PDF file. Returns the path."""
    return html_to_pdf(generation_to_html(generation, trend=trend, app_name=app_name), out_path)
