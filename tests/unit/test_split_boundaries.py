"""3-repo split boundary guards.

Before the monorepo splits into `glimi` (kernel) / `glimi-community` (src/) /
`glimi-workspace` (apps/workspace/), the import boundaries must hold so each
piece can stand alone depending only on the *published* `glimi` public API:

  - the kernel (`glimi/`) imports no app code (`src.*` / `apps.*`);
  - the apps never reach into underscore-private `glimi` internals (those can
    change on any kernel release);
  - `apps/workspace` never imports `src.*` (and vice-versa).

These are AST checks (docstring mentions don't count). Keep them green and the
split stays push-button — see SPLIT_PLAN.md.
"""
from __future__ import annotations

import ast
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _py_files(rel: str):
    base = os.path.join(_ROOT, rel)
    for dirpath, _dirs, files in os.walk(base):
        if "/." in dirpath or "__pycache__" in dirpath:
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _imports(path: str):
    """Yield (lineno, module, [names]) for every import in the file."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            yield n.lineno, n.module, [a.name for a in n.names]
        elif isinstance(n, ast.Import):
            for a in n.names:
                yield n.lineno, a.name, []


def _top(mod: str) -> str:
    return (mod or "").split(".")[0]


def test_kernel_imports_no_app_code():
    bad = [
        f"{p}:{ln} {mod}"
        for p in _py_files("glimi")
        for ln, mod, _ in _imports(p)
        if _top(mod) in ("src", "apps")
    ]
    assert not bad, "glimi/ must not import app code (src/apps):\n" + "\n".join(bad)


def test_workspace_does_not_import_src():
    bad = [
        f"{p}:{ln} {mod}"
        for p in _py_files("apps/workspace")
        for ln, mod, _ in _imports(p)
        if _top(mod) == "src"
    ]
    assert not bad, "apps/workspace must not import src.* :\n" + "\n".join(bad)


def test_community_does_not_import_apps():
    bad = [
        f"{p}:{ln} {mod}"
        for p in _py_files("src")
        for ln, mod, _ in _imports(p)
        if _top(mod) == "apps"
    ]
    assert not bad, "src/ must not import apps.* :\n" + "\n".join(bad)


def test_apps_use_only_public_glimi_api():
    """Apps must import public (non-underscore) symbols from glimi, so they don't
    break when kernel internals change across a published release."""
    bad = []
    for rel in ("src", "apps/workspace"):
        for p in _py_files(rel):
            for ln, mod, names in _imports(p):
                if _top(mod) == "glimi":
                    for nm in names:
                        if nm.startswith("_"):
                            bad.append(f"{p}:{ln} from {mod} import {nm}")
    assert not bad, (
        "apps import underscore-private glimi internals (promote to public API "
        "first — see SPLIT_PLAN.md Phase 1):\n" + "\n".join(bad)
    )
