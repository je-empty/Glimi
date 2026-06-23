# QA generations — the git-tracked quality timeline

Each `gen-NNNN-<ts>-<sha>.json` here is **one QA generation**: a multi-dimension
quality assessment of one end-to-end community run, stamped with the **git SHA** it
ran against. Written by `tests/e2e/qa_history.py` when a run uses `--qa`.

These are committed on purpose — together they form a measurable, git-visible record
of the product's quality climbing over generations (the eval flywheel). See
[`docs/qa_system.md`](../../docs/qa_system.md).

```bash
git log -- tests/e2e/qa_generations/   # the quality timeline
git log --grep "qa:"                   # every quality-affecting change, with its score delta
```

The full queryable history (for the web dashboard + trends) lives in
`tests/e2e/results/qa_history.db` (SQLite, gitignored — local artifact).
