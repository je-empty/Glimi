# Glimi → 3-repo split — prep plan

> **STATUS (2026-06-19): DEFERRED — staying monorepo for now.** After weighing it,
> the decision is to keep a **single monorepo** (the hero repo, concentrates
> stars/attention) and **publish the `glimi` package to PyPI straight from it**
> (its `pyproject` already builds only `glimi/` — like LangChain/LlamaIndex publish
> many packages from one repo). The 3-repo split below is **fully prepped but not
> executed**; revive it only if there's a concrete reason (e.g. a separate product).
> If reviving: author the per-repo `split/README.*` + `split/CLAUDE.*` first
> (workflow output saved), then run `split/split.sh`.

Goal (if/when revived): split this monorepo into three standalone repos, each
buildable on its own, with the two apps depending on the **published `glimi`**
package (not on each other's source).

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

## Phase 2 — Shared UI in `glimi/dashboard` ✅ DONE (kernel + workspace) · ⏳ community template deferred

The **rich** dashboard UI is now the single source in `glimi`. Resolved the open
"degrade vs ship-both" question: **one rich client, capability-driven** — the kernel
ships the rich `dashboard.js`/`css` + the canonical shell template and renders it on
a bare store via `enrich_snapshot`; apps switch behaviour by render context, never by
forking markup.

Done:
- ✅ Canonical in `glimi/dashboard`: `dashboard.js` (rich, replaced the minimal one), `dashboard.css`, `dashboard-chat.css`, `base.css`, `tokens.css`, `chat.js`/`chat.css`, `i18n/dashboard.{en,ko}.json`, and the shared templates `templates/dashboard/_core.html` (parameterized shell — `static_base`/`api_base`/`caps_json`/`community_chrome`/`active_tab`, with `extra_head`/`extra_chrome`/`extra_modals`/`extra_scripts` hooks) + `templates/_chat_shell.html`.
- ✅ Kernel demo (`glimi.dashboard.serve()` / `create_app`) renders `_core.html` with kernel-default caps (opens on Overview, chat-less) and serves the enriched snapshot + `/api/i18n`. `import glimi.dashboard` stays zero-dep (guarded).
- ✅ Snapshot enricher promoted to `glimi.dashboard.enrich_snapshot` (pure, zero-dep) — kernel + workspace both use it (workspace `_snapshot_payload` is now a thin alias).
- ✅ Workspace **fully consumes** the package: renders `dashboard/_core.html` (multi-dir Jinja: app `templates/` + the package `templates/`), serves `/static` from `glimi/dashboard/static`, loads i18n from `glimi/dashboard/i18n`. Deleted ALL vendored copies (`apps/workspace/static`, `apps/workspace/i18n`, `templates/{base,dashboard/index,_chat_shell,ws_dashboard}.html`) + the `/wstatic` mount + dead `_index_html_for`/`_ws_dashboard_html_for`. Only `home.html` stays workspace-local.
- ✅ Retired the kernel minimal `templates/index.html`.
- ✅ `tests/unit/test_chat_asset_single_source.py` re-anchored: community = byte-identical synced copies of the canonical (assets + i18n); workspace holds **no** copies (static/i18n/dashboard-template). `pyproject.toml` package-data already ships templates(+nested)/static/i18n.

✅ Community also migrated (2026-06-19): `src/platform/templates/dashboard/index.html`
is now a thin `{% extends "dashboard/_core.html" %}` rendered with `community_chrome=True`
+ all caps. The Discord bot-lifecycle / damage-recovery script lives in a community
partial (`_community_server_control.html`) filled into `extra_scripts`; PWA into
`extra_head`; sync-modal + boot overlay into `extra_modals`; the server-control
buttons (`gp-server-ctrl`) into `extra_chrome` — **none of it in Core**. `templates/__init__.py`
adds the package template dir to the Jinja search path. Community still serves its own
`/static` copies (test-guarded == canonical; its SW/cache-busting hangs off that path).
Verified on a scratch demo instance: full chrome (switcher / 가동 / lang / supervisor /
elastic / Discord+Scene KPIs), all 13 tabs, graph, chat, no console errors — pixel-identical
to before. The behaviour is neutral, so the live community adopts it on its next restart
(its running process has the old template cached until then — no live disruption needed).

> All three apps now consume the single canonical `glimi[dashboard]` UI. Template
> duplication is gone; only `home.html` (workspace) + the non-dashboard community
> pages keep their own templates.

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

Pre-split fixes the script assumes:
- **5.1** ✅ Verified **not a blocker**: `split.sh` keeps `src/` at the community repo root (`--path src/`, no rename), so `config.py`'s `parent.parent.parent` (and `routers/dashboard.py`/`dashboard/api.py` `parent×4`) resolve to the repo root at the **same depth** pre- and post-split. `GLIMI_DATA_DIR` already overrides the data dir. No change needed.
- **5.2** ✅ `src/platform/demo_seed.py` does `from scripts.seed_demo_mockup import seed`; `scripts/` is an implicit namespace package (no `__init__`, works from repo root) and `split.sh` includes `scripts/seed_demo_mockup*.py`. Fine standalone.
- **5.3** ✅ Done in Phase 2 — workspace dead code (`ws_dashboard.html`, `_ws_dashboard_html_for`, `_index_html_for`, vendored static/templates/i18n) removed; `_avatar_svg`/`_esc`/`_monogram` kept.

🔒 Never-leak (verify not tracked in any extract; `.gitignore`d but double-check): `CLAUDE.local.md`, `communities*/`, `data*/`, `.env*` (except `.env.example`), `analysis/`, `.claude/`, `eval/reports/`, LoRA `*.safetensors`. Explicit scrub of tracked personal docs under `docs/` (`docs/[0-9][0-9]_*`, `*지시서*`) handled by the community filter's invert pass.

---

## Ownership model (2026-06-19)
- **`glimi` (core) + `glimi-workspace` = owner-only** (jbsim). No external contributors.
- **`glimi-community` = the contributor repo** — content owner + maintainer. All
  collaboration infra lives here only.
- **A path-based `git filter-repo` keeps each repo's history scoped to its own tree** — core/workspace and community separate cleanly with no manual scrub.
- `split.sh` already routes contributor docs (`START_HERE.html`/`COLLAB_GUIDE.html`/`CONTRIBUTING.md`) to community **only**; core/workspace don't get them. ✓
- ⚠ **Gaps to handle (owner or a follow-up pass):**
  - **Per-repo `CLAUDE.md`**: `split.sh` routes `CLAUDE.md` to **no** repo → all 3 split repos would lack project instructions. Author 3: community = current rules (branch strategy / COLLAB_GUIDE ref / area ownership / design-system / prompts); `glimi` = core-only short version (zero-dep purity, decoupling, prompt rules, commit/author rules) **without the external-contributor section**; `glimi-workspace` = short owner-only version. (`CLAUDE.local.md` stays untracked, never split.)
  - **`COLLAB_GUIDE.html` part-map** currently lists "core / engine / platform" review areas; post-split those aren't in the community repo (it depends on `glimi[dashboard]`). Trim to community-content areas only.

## Phase 6 — 👤 OWNER actions (after the script)
- Create the 3 GitHub repos (`glimi` public for OSS; community/workspace per the visibility decision). core + workspace = owner-only access; community = add the content contributor.
- Add remotes, push; enable CI; publish `glimi` to PyPI.
- Move repo-specific GitHub settings (branch protection on community; secrets).
