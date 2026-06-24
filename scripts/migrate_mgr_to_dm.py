#!/usr/bin/env python3
"""One-off migration: rename legacy mgr-* manager channels to dm-<name> and drop
the mgr-system-log channel, so every community matches the web-first model
(managers are DMs like everyone else).

  mgr-dashboard    -> dm-<norm(mgr.name)>
  mgr-creator      -> dm-<norm(creator.name)>
  mgr-dev-request  -> dm-<norm(dev.name)>
  mgr-system-log   -> deleted (its rows are <tools> logs, kept in logs/system.log)

Renames both conversations.channel and channels.channel. Backs up each DB first.
Idempotent: skips channels that don't exist; merges if the dm- target already exists.

Usage:  python scripts/migrate_mgr_to_dm.py [communities_dir]   (default: ./communities)
"""
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _norm(name: str) -> str:
    s = re.sub(r"\s+", "-", (name or "").strip())
    s = re.sub(r"[^\w\-가-힣ㄱ-ㅎㅏ-ㅣ]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


OLD_BY_TYPE = {"mgr": "mgr-dashboard", "creator": "mgr-creator", "dev": "mgr-dev-request"}


def _rename(conn: sqlite3.Connection, old: str, new: str) -> str:
    cur = conn.execute("SELECT 1 FROM channels WHERE channel=?", (old,)).fetchone()
    has_conv = conn.execute("SELECT 1 FROM conversations WHERE channel=? LIMIT 1", (old,)).fetchone()
    if not cur and not has_conv:
        return ""  # nothing to do
    target_exists = conn.execute("SELECT 1 FROM channels WHERE channel=?", (new,)).fetchone()
    conn.execute("UPDATE conversations SET channel=? WHERE channel=?", (new, old))
    if target_exists:
        conn.execute("DELETE FROM channels WHERE channel=?", (old,))  # merge into existing dm-
        return f"{old} → {new} (merged; {conn.total_changes} rows)"
    conn.execute("UPDATE channels SET channel=? WHERE channel=?", (new, old))
    return f"{old} → {new}"


def migrate_db(db: Path) -> list[str]:
    log: list[str] = []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        agents = {r["type"]: r["name"] for r in
                  conn.execute("SELECT type, name FROM agents").fetchall()}
        for atype, old in OLD_BY_TYPE.items():
            name = agents.get(atype)
            if not name:
                continue
            new = f"dm-{_norm(name)}"
            if new == old:
                continue
            r = _rename(conn, old, new)
            if r:
                log.append(r)
        # drop the system-log channel + its (tool-log) rows
        sl_conv = conn.execute("DELETE FROM conversations WHERE channel='mgr-system-log'")
        sl_ch = conn.execute("DELETE FROM channels WHERE channel='mgr-system-log'")
        if sl_conv.rowcount or sl_ch.rowcount:
            log.append(f"dropped mgr-system-log ({sl_conv.rowcount} msgs)")
        conn.commit()
    finally:
        conn.close()
    return log


def main(base: str):
    root = Path(base)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if not root.exists():
        print(f"no such dir: {root}")
        return
    for cdir in sorted(root.iterdir()):
        db = cdir / "community.db"
        if not db.is_file():
            continue
        bdir = cdir / "backups"
        bdir.mkdir(exist_ok=True)
        shutil.copy2(db, bdir / f"community.db.pre-dm-migration-{ts}")
        log = migrate_db(db)
        if log:
            print(f"[{cdir.name}] " + "; ".join(log))
        else:
            print(f"[{cdir.name}] (no legacy mgr-* channels)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "communities")
