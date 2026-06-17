"""``python -m eval <command>`` dispatcher.

Commands:
  run       run the golden-set eval (``--backend echo|claude_cli|ollama``)
  gate      regression gate vs eval/baseline.json
  baseline  freeze the current run as the new baseline
  promote   promote flagged production turns (JSONL) into golden cases
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "run"
    rest = argv[1:]

    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if cmd == "run":
        from .runner import main as run_main
        return run_main(rest)
    if cmd == "gate":
        from .regression import main as gate_main
        return gate_main(rest)
    if cmd == "baseline":
        from .regression import write_baseline
        import argparse
        ap = argparse.ArgumentParser(prog="eval baseline")
        ap.add_argument("--backend", default="echo")
        ap.add_argument("--out", default=None)
        a = ap.parse_args(rest)
        from pathlib import Path
        p = write_baseline(backend=a.backend, out_path=Path(a.out) if a.out else None)
        print(f"baseline written: {p}")
        return 0
    if cmd == "promote":
        from .from_production import main as promote_main
        return promote_main(rest)

    print(f"unknown command: {cmd!r}\n")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
