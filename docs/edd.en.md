# EDD — eval-driven development (quality tracked per commit)

[← README](../README.md)

Multi-agent products are hard to measure; perception isn't data. Glimi applies **EDD — eval-driven development**. An autonomous **owner agent** runs the app from onboarding to core flow. Each run produces **weighted dimension scores** and a **0–100 composite**, committed as a **git-SHA generation**. `git log` becomes a quality timeline where each commit shows its score. The **`glimi.edd`** module in the `glimi` kernel supports this for both Community and Workspace, each defining its own dimensions and owner agent.

**Scoring**: each dimension 0–10 with a weight; the composite is a weighted average normalized to 0–100. `critical` = any fail voids the run. LLM-judge dimensions are **skipped** on `echo` or when no judge exists. Community defines six dimensions:

| Dimension | Kind | Weight | Critical | What it checks |
|---|---|:--:|:--:|---|
| `onboarding` | structural | 1.0 | | A fresh owner greets the manager and gets oriented |
| `friend_creation` | structural | 1.5 | ⭐ | An owner request actually creates a new friend, and conversation follows |
| `conversation_quality` | LLM-judge | 2.0 | | Replies are human, coherent, in-character (5 axes: in_character · coherence · naturalness · engagement · no_meta) |
| `no_hallucination` | LLM-judge | 1.5 | | No invented facts, no claiming actions it never took |
| `no_leaks` | structural | 1.0 | | Zero meta / error / tool-block leakage into chat |
| `responsiveness` | structural | 1.0 | | Every driven DM gets a distinct reply, no stalls |

## The flywheel, with real measurements

**Repo generations** (`tests/e2e/qa_generations/*.json`) are real `claude_cli` runs scored by the judge and tagged with a git SHA. Data is small because the system is new. The aim is to accumulate scored generations, not depth of history.

| Gen | git SHA | Branch | Composite / 100 | Verdict | `conversation_quality` | `friend_creation` (critical) | Failing |
|:--:|:--:|---|:--:|:--:|:--:|:--:|---|
| **1** | `1eb4c46`* | `feat/community-qa-system` | **69.4** | ❌ FAIL | 6.0 | **0.0** | friend_creation, conversation_quality |
| **2** | `b3eaf74`* | `feat/community-qa-system` | **75.0** | ❌ FAIL | **9.0** ▲ | **0.0** | friend_creation *(composite ≥ 70, but critical = 0)* |
| **3** | `f1eb58a`* | `develop` | **72.5** | ❌ FAIL | 8.0 | **0.0** | friend_creation *(composite ≥ 70, but critical = 0)* |
| **4** | `f1eb58a`* | `develop` | **56.9** | ❌ FAIL | 4.0 ▼ | **0.0** | friend_creation, conversation_quality, no_hallucination |
| **5** | `217de05`* | `feat/web-native-onboarding` | **77.5** | ✅ **PASS** | 6.0 | **10.0** ▲▲ | — *(first PASS)* |
| ⋯ | gens 6–10 | `217de05` → `a8d874d` | 57.8 ↘ 22.2 ↗ 57.8 | ❌ FAIL (regressed) | — | **0.0** ▼ | friend_creation |
| **11** | `a8d874d`* | `feat/web-native-onboarding` | **85.0** | ✅ **PASS** | 7.0 | **10.0** ▲▲ | — *(highest)* |

`*` = dirty working tree during run. All values come from committed JSON. **First PASS was gen-5** (`217de05`, 77.5): web-native onboarding lifted critical `friend_creation` 0 → 10. It regressed to 0 across gens 6–10, then held at 10 in gen-11 (`a8d874d`, **85.0 — the highest**).

Failures shown for clarity:

- **`conversation_quality` 6 → 9 → 8 → 4 → 7** shows LLM variance. Gen-1→2 fixed manager loops; gen-4 regressed; gen-11 stabilized at 7.
- **`friend_creation` (critical) was 0 for gens 1–4 and 6–10, and 10 at gen-5 and gen-11**—the expected fail came from subprocess isolation in the old bootstrap adapter (see [`docs/qa_system.md`](qa_system.md), `analysis/platform_decoupling_review.md`). Web-native onboarding first cleared it at **gen-5 (77.5, first ✅ PASS)**; after a regression across gens 6–10 it was restored at **gen-11 (85.0, the highest)**. `conversation_quality` 7 and `no_hallucination` 6 stay exposed.
- **Composite ≥ 70 is not enough.** Gens 2 (75.0) and 3 (72.5) cleared the threshold but still FAILED on `friend_creation` = 0 — a high chat score can't outvote a broken critical journey. That is the gate working as designed.

Core rule: **git tracks product quality**. Each commit's impact appears in history. The dashboard and PDF below visualize it.

## See it: the `/admin/qa` dashboard + PDF reports

A **QA dashboard** at `/admin/qa` (admin → "QA") shows the latest composite, **trend chart**, and per-generation breakdown. Any run exports to **PDF** via `glimi.edd.report`, which prints through Playwright. The trend SVG is server-rendered for consistent output.

![EDD — /admin/qa dashboard: gen-11 PASS 85, the dimension breakdown, and the quality-over-generations trend](screenshots/en/19-edd-dashboard.png)

```bash
# one scored generation (free self-test: echo backend, judge skipped, structural dims only)
GLIMI_LLM_BACKEND=echo .venv/bin/python -m tests.e2e.community_e2e --owner-agent --rounds 2 --qa

# a real, judged generation → SQLite + a committable gen-NNNN-*.json
GLIMI_LLM_BACKEND=claude_cli .venv/bin/python -m tests.e2e.community_e2e \
    --owner-agent --rounds 10 --qa --report

# + a PDF report (trend chart + dimensions; needs Playwright). --pdf implies --qa.
GLIMI_LLM_BACKEND=claude_cli .venv/bin/python -m tests.e2e.community_e2e \
    --owner-agent --rounds 10 --pdf --report
```

```bash
git log -- tests/e2e/qa_generations/   # the quality timeline (committed generations)
git log --grep "qa:"                   # every quality-affecting change, with its score delta
```

**For adopters:** `glimi.edd` is domain-neutral in the `glimi` wheel. Add your dimensions and owner-agent driver for composite scoring, git-anchored SQLite + JSON storage, and HTML/PDF reports.

```python
from glimi.edd import Dimension, DimResult, build_assessment, GenerationStore

DIMS = [Dimension("onboarding", "Onboarding", 1.0, "structural", "fresh user gets oriented"),
        Dimension("core_journey", "Core journey", 1.5, "structural", "...", critical=True)]
results = [DimResult.for_dim(d, score=..., passed=..., detail="...") for d in DIMS]  # you evaluate
assessment = build_assessment(results, min_overall=70)                              # core scores → 0–100
store = GenerationStore(db_path="qa.db", generations_dir="qa_generations/")          # core persists
store.record(assessment.as_dict(), run_id="run-1")                                   # → SQLite + git-SHA JSON
```

Community uses six dimensions on this core. Workspace reuses `glimi.edd` with deliverable / delegation / A2A dimensions. One framework powers both apps. Full spec: [`docs/qa_system.md`](qa_system.md).
