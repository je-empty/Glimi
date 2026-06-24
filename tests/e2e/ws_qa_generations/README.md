# Workspace QA generations — the git-tracked quality timeline

Each `gen-NNNN-<ts>-<sha>.json` here is **one Workspace QA generation**: a
multi-dimension quality assessment of one end-to-end workspace run (owner ↔ team),
stamped with the **git SHA** it ran against. Written by `tests/e2e/ws_qa_history.py`
when a run uses `--qa`.

These are committed on purpose — together they form a measurable, git-visible record
of the workspace product's quality climbing over generations (the eval flywheel).
This is the Workspace analogue of `tests/e2e/qa_generations/` (Community).

```bash
git log -- tests/e2e/ws_qa_generations/   # the workspace quality timeline
```

The full queryable history (for the web dashboard + trends) lives in
`tests/e2e/results/ws_qa_history.db` (SQLite, gitignored — local artifact).
