# Glimi → 3-repo split — prep plan

Goal: split this monorepo into three standalone repos, each buildable on its own,
with the two apps depending on the **published `glimi`** package (not on each
other's source).

| Repo | Contents | Depends on |
|---|---|---|
| **`glimi`** (kernel, → PyPI) | `glimi/` + `eval/` + kernel tests | nothing (zero-dep core; `glimi[dashboard]` = fastapi/uvicorn/jinja2) |
| **`glimi-community`** (flagship app) | `src/` + root `i18n/` + `assets/` + `resources/` + community tests | `glimi[dashboard]` + discord.py etc. |
| **`glimi-workspace`** (work app) | `apps/workspace/` (hoisted to root) + workspace tests | `glimi[dashboard]` |

Authored from the `split-readiness-audit` workflow (4 parallel audits + architect plan).
Run the split with `split/split.sh` **only after** everything marked DONE here is
merged to `develop` and CI is green.

---

## Status legend
✅ DONE (landed in-monorepo) · ⏳ REMAINING (do before split) · 👤 OWNER (human action)

---

## Phase 1 — Decoupling: apps consume only public `glimi` API ✅ DONE

The hard blockers — apps must not reach into underscore-private kernel internals
(they'd break on any kernel release). Promoted to public API + switched consumers:

- ✅ `glimi.llm.find_claude` (was `_find_claude`) — consumer `src/platform/setup.py`.
- ✅ `glimi.dashboard.owner_info` / `channel_detail` (were `glimi.dashboard.app._owner_info/_channel_detail`; moved to the zero-dep `reader`, re-exported from `glimi.dashboard`) — consumer `apps/workspace/server.py`.
- ✅ `glimi.tools.registry.env_truthy` (was `_env_truthy`) — consumers `src/core/prompts/en/creator.py`, `src/bot/tool_handlers.py`.
- ✅ `glimi.transport.__all__` declared (Speaker/ImagePart/Outbox/Inbox/InboundMessage).
- ✅ Stale kernel docstring `from src.llm import generate` → `from glimi.llm import generate`.
- ✅ **Regression gate:** `tests/unit/test_split_boundaries.py` — AST-asserts (a) kernel imports no `src`/`apps`, (b) `apps/workspace` never imports `src`, (c) `src` never imports `apps`, (d) apps import only non-underscore `glimi` symbols. Kept green keeps the split push-button.

Verified: `import glimi` (all submodules) leaks **zero** `src`/`apps`/`fastapi` modules (kernel purity intact).

Optional polish (non-blocking — these are public-submodule, not underscore-private):
- ⏳ `src/platform/routers/chat.py` `from glimi import memory; memory.record_reaction_signal` → re-export `glimi.record_reaction_signal`.
- ⏳ `apps/workspace/demo.py` deep `glimi.llm.pricing.estimate_tokens_from_chars` (already try/except-guarded) → re-export from `glimi.llm`.

---

## Phase 2 — Shared UI in `glimi/dashboard` ⏳ REMAINING (the one risky piece)

For a clean split the **rich** dashboard UI must be the single source in `glimi`
so both apps consume `glimi[dashboard]` rather than vendoring copies.

Today:
- ✅ `chat.js` / `chat.css` already canonical in `glimi/dashboard/static` (apps consume it; community keeps a CI-guarded synced copy).
- ✅ The workspace already **renders** the rich Community dashboard (config-driven `dashboard.js`: `API_BASE` + `data-caps`), via a CI-guarded synced copy in `apps/workspace/static` (community is the source). i18n + monogram avatars + KO/EN picker work.
- ⏳ The rich `dashboard.js`(3875)/`dashboard.css`(1736)/`base.css`/`dashboard-chat.css`/`tokens.css`(reconcile 169 vs kernel 120)/`base.html`/`_chat_shell.html`/rich `dashboard/index.html`/`i18n/dashboard.*.json` still live in `src/platform` (master) + `apps/workspace` (copy). The kernel ships only a **minimal** 720-line `dashboard.js`.

To finish (sequence so tests stay green at every step):
1. Copy the rich masters into `glimi/dashboard/static` + `glimi/dashboard/templates/` + `glimi/dashboard/i18n/`, **reconciling** `tokens.css` (adopt the 169-line superset; verify the kernel `dashboard.css` needs no dropped token).
2. **Decide (open question):** *one rich client that degrades* on the kernel's bare `serve()` (no community endpoints) — preferred, single artifact — **vs** *ship both* (rich for apps + keep minimal `dashboard.min.js` for `glimi.dashboard.serve`). Verify the rich client renders read-only on a bare `DashboardReader` app **without console errors** (highest-risk step) before retiring the minimal one.
3. Point both apps at the shared mount; delete the app-owned copies (`apps/workspace/static/{js/dashboard.js,css/dashboard.css,dashboard-chat.css,base.css,tokens.css}`, `apps/workspace/i18n/`, and the equivalents community would otherwise carry). Render the glimi-shipped templates via each app's Jinja env (resolve the package template dir via `glimi.dashboard.__path__`).
4. Re-anchor `tests/unit/test_chat_asset_single_source.py` to assert apps hold **no** dashboard copies (mirror `test_workspace_keeps_no_chat_copy`).
5. ✅ `pyproject.toml` package-data already extended (`templates/**/*.html`, `i18n/*.json`) so the assets will ship.

> Until Phase 2 lands, the split still produces working repos — community + workspace
> each carry a (guarded, identical) dashboard copy. Phase 2 removes that duplication
> so both consume one `glimi[dashboard]`.

---

## Phase 3 — Packaging ✅ staged

- ✅ Kernel `pyproject.toml` (this repo's live one): `name=glimi`, `dependencies=[]`, extras `sdk` + `dashboard` (`fastapi/uvicorn[standard]/jinja2`); package-data ships `glimi.dashboard` templates(+nested)/static/i18n. (Community/imagegen extras move to the community repo — see staged file.)
- ✅ `split/pyproject.community.toml` — `glimi-community`, deps `glimi[dashboard]` + discord.py/dotenv/itsdangerous/multipart/rich/Pillow/textual; `imagegen` extra.
- ✅ `split/pyproject.workspace.toml` — `glimi-workspace`, deps `glimi[dashboard]` + python-multipart + httpx; flat layout (`python run.py`, tests `import server`).
- Local dev (no PyPI round-trip): each app repo `requirements-dev.txt` = `-e ../glimi[dashboard]` + `-e .`.
- 👤 Publish `glimi 0.1.0` to (Test)PyPI so the app repos resolve `glimi[dashboard]` in CI; until then their CI checks out + `pip install -e` the kernel path.

---

## Phase 4 — Per-repo CI ✅ staged
`split/ci.kernel.yml`, `split/ci.community.yml`, `split/ci.workspace.yml`. Test buckets:
- **kernel:** `test_glimi_*` (minus the cross-layer `test_glimi_dashboard.py`), `test_reactions_kernel`, `test_tool_call_capture`, `test_llm_usage_sink`, `test_eval_harness`, `test_split_boundaries`, plus `eval run --backend echo`.
- **workspace:** `test_workspace_*`, `test_glimi_workspace`.
- **community:** everything else (incl. cross-layer `test_glimi_dashboard`, `test_budget_guard`, `test_web_chat_*`, `test_chat_asset_single_source`).

---

## Phase 5 — The split script ✅ `split/split.sh`
`git filter-repo` extracts each tree with history into `/tmp/glimi-split/{glimi,glimi-community,glimi-workspace}`, drops the staged pyproject/CI, hoists `apps/workspace/`→root, and runs a >5MB blob audit. Review the output, then add remotes + push.

⏳ Pre-split fixes the script assumes (do before running):
- **5.1** `src/platform` repo-root traversals (`config.py`, `dashboard/api.py`, `routers/dashboard.py` `PROJECT_ROOT`) — make env-driven / single `_repo_root()` helper so they work at standalone depth.
- **5.2** `src/platform/demo_seed.py` imports `scripts.seed_demo_mockup` — the community filter in `split.sh` already includes `scripts/seed_demo_mockup*.py` (confirm path).
- **5.3** Delete workspace dead code (`ws_dashboard.html`, `_ws_dashboard_html_for`, `_WS_DASH_HTML`, `_CHAT_SHELL_HTML`) once Phase 2 lands — keep `_avatar_svg`/`_esc`.

🔒 Never-leak (verify not tracked in any extract; `.gitignore`d but double-check): `CLAUDE.local.md`, `communities*/`, `data*/`, `.env*` (except `.env.example`), `analysis/`, `.claude/`, `eval/reports/`, LoRA `*.safetensors`. Explicit scrub of tracked personal docs under `docs/` (`docs/[0-9][0-9]_*`, `*지시서*`) handled by the community filter's invert pass.

---

## Phase 6 — 👤 OWNER actions (after the script)
- Create the 3 GitHub repos (`glimi` public for OSS; community/workspace per the visibility decision).
- Add remotes, push; enable CI; publish `glimi` to PyPI.
- Move repo-specific GitHub settings (branch protection, secrets).
