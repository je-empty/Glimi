#!/usr/bin/env bash
# Glimi monorepo → 3 standalone repos (glimi / glimi-community / glimi-workspace),
# preserving history per tree. Produces clones under $OUT; review, then add remotes
# + push. Idempotent-ish: it wipes $OUT first. See SPLIT_PLAN.md.
#
#   ./split/split.sh [OUT_DIR]      # default OUT=/tmp/glimi-split
#
# Prereq: git-filter-repo (brew install git-filter-repo) and a clean, committed
# working tree on the branch you want to extract.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-/tmp/glimi-split}"

command -v git-filter-repo >/dev/null 2>&1 || {
  echo "ERROR: git-filter-repo not found. Install: brew install git-filter-repo"; exit 1; }
[ -z "$(git -C "$SRC" status --porcelain)" ] || {
  echo "ERROR: working tree not clean — commit/stash first."; exit 1; }

echo "Source : $SRC"
echo "Output : $OUT"
rm -rf "$OUT"; mkdir -p "$OUT"

# ── Repo A: kernel (glimi) ──────────────────────────────────────────────────
git clone --no-local "$SRC" "$OUT/glimi"
( cd "$OUT/glimi"
  git filter-repo \
    --path glimi/ --path eval/ \
    --path PYPI_README.md --path LICENSE --path pyproject.toml \
    --path docs/screenshots/ --path resources/ \
    --path tests/__init__.py --path tests/unit/__init__.py \
    --path-glob 'tests/unit/test_glimi_*.py' \
    --path tests/unit/test_reactions_kernel.py \
    --path tests/unit/test_tool_call_capture.py \
    --path tests/unit/test_llm_usage_sink.py \
    --path tests/unit/test_eval_harness.py \
    --path tests/unit/test_split_boundaries.py \
    --invert-paths --path tests/unit/test_glimi_dashboard.py   # cross-layer → community
  mkdir -p .github/workflows
  cp "$SRC/split/ci.kernel.yml" .github/workflows/ci.yml
  # pyproject.toml is already the trimmed kernel one (lives in the monorepo).
  # The kernel (Core) README is the portfolio entry point: links out to the two
  # app repos + embeds docs/screenshots. CLAUDE.md = owner-only kernel rules.
  # Per-repo README/CLAUDE are staged-pending (monorepo is the current shape; the
  # split is deferred — see SPLIT_PLAN.md). Author split/README.kernel*.md +
  # split/CLAUDE.kernel.md before a real split (workflow output saved). Fail-soft.
  cp "$SRC/split/README.kernel.md"     README.md       2>/dev/null || true
  cp "$SRC/split/README.kernel.ko.md"  README.ko.md    2>/dev/null || true
  cp "$SRC/split/CLAUDE.kernel.md"     CLAUDE.md        2>/dev/null || true
  cp "$SRC/NOTICE"                     NOTICE          2>/dev/null || true
  cp "$SRC/CITATION.cff"               CITATION.cff    2>/dev/null || true
  git add -A && git commit -q -m "chore: kernel CI + README/CLAUDE + NOTICE for standalone repo" || true )

# ── Repo C: workspace (glimi-workspace) ─────────────────────────────────────
git clone --no-local "$SRC" "$OUT/glimi-workspace"
( cd "$OUT/glimi-workspace"
  git filter-repo \
    --path apps/workspace/ \
    --path tests/__init__.py --path tests/unit/__init__.py \
    --path tests/unit/test_workspace_approval.py \
    --path tests/unit/test_workspace_demo.py \
    --path tests/unit/test_workspace_server.py \
    --path tests/unit/test_glimi_workspace.py \
    --path-rename apps/workspace/:        # hoist to repo root
  cp "$SRC/split/pyproject.workspace.toml" pyproject.toml
  cp "$SRC/LICENSE" LICENSE 2>/dev/null || true
  cp "$SRC/split/README.workspace.md" README.md       2>/dev/null || true
  cp "$SRC/split/CLAUDE.workspace.md"  CLAUDE.md        2>/dev/null || true
  mkdir -p .github/workflows
  cp "$SRC/split/ci.workspace.yml" .github/workflows/ci.yml
  git add -A && git commit -q -m "chore: workspace pyproject + CI + README/CLAUDE for standalone repo" )

# ── Repo B: community (glimi-community) ──────────────────────────────────────
git clone --no-local "$SRC" "$OUT/glimi-community"
( cd "$OUT/glimi-community"
  git filter-repo \
    --path src/ --path i18n/ --path assets/ --path resources/ --path examples/ \
    --path scripts/seed_demo_mockup.py --path scripts/seed_demo_mockup_en.py \
    --path requirements.txt --path README.md --path README.ko.md \
    --path START_HERE.html --path COLLAB_GUIDE.html --path CONTRIBUTING.md \
    --path run.sh --path run.bat --path bootstrap.sh --path docs/ \
    --path tests/__init__.py --path tests/unit/__init__.py --path tests/e2e/ \
    --path-glob 'tests/unit/test_*.py'
  # second pass: drop kernel/workspace-only tests + personal docs + any apps leak
  git filter-repo --force --invert-paths \
    --path-glob 'tests/unit/test_glimi_context_budget.py' \
    --path-glob 'tests/unit/test_glimi_dashboard_web.py' \
    --path-glob 'tests/unit/test_glimi_memory*.py' \
    --path-glob 'tests/unit/test_glimi_runtime_tz.py' \
    --path-glob 'tests/unit/test_glimi_store_contract.py' \
    --path-glob 'tests/unit/test_glimi_supersession.py' \
    --path-glob 'tests/unit/test_glimi_tools.py' \
    --path-glob 'tests/unit/test_reactions_kernel.py' \
    --path-glob 'tests/unit/test_tool_call_capture.py' \
    --path-glob 'tests/unit/test_llm_usage_sink.py' \
    --path-glob 'tests/unit/test_eval_harness.py' \
    --path-glob 'tests/unit/test_split_boundaries.py' \
    --path-glob 'tests/unit/test_workspace_*.py' \
    --path-glob 'tests/unit/test_glimi_workspace.py' \
    --path-glob 'docs/[0-9][0-9]_*' \
    --path-glob 'docs/*지시서*.md' \
    --path apps/
  cp "$SRC/split/pyproject.community.toml" pyproject.toml
  cp "$SRC/LICENSE" LICENSE 2>/dev/null || true
  # Overwrite the monorepo README the filter carried in with the community one.
  cp "$SRC/split/README.community.md"    README.md       2>/dev/null || true
  cp "$SRC/split/README.community.ko.md" README.ko.md    2>/dev/null || true
  cp "$SRC/split/CLAUDE.community.md"     CLAUDE.md        2>/dev/null || true
  mkdir -p .github/workflows
  cp "$SRC/split/ci.community.yml" .github/workflows/ci.yml
  git add -A && git commit -q -m "chore: community pyproject + CI + README/CLAUDE for standalone repo" )

# ── safety: large blobs + leaked private files per extract ──────────────────
for r in glimi glimi-workspace glimi-community; do
  echo "== $r: blobs >5MB =="
  ( cd "$OUT/$r" && git rev-list --objects --all \
      | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' 2>/dev/null \
      | awk '$1=="blob" && $2>5000000 {print $2, $3}' | sort -n || true )
  echo "== $r: private-file leak check =="
  ( cd "$OUT/$r" && git ls-files | grep -E 'CLAUDE\.local|/\.env($|[^.])|communities/|data/|analysis/|\.safetensors$' || echo "  clean" )
done

echo
echo "Done. Review $OUT/{glimi,glimi-community,glimi-workspace}."
echo "Then per repo: git remote add origin <url> && git push -u origin main"
