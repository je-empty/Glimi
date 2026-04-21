#!/usr/bin/env python3
"""DB 타임스탬프 KST/UTC naive → UTC aware 일괄 마이그레이션.

**왜 필요한가**
- 기존 코드: `datetime.now().isoformat()` = 로컬(KST) naive. `2026-04-22T23:30:22.123456`
- 기존 코드: SQLite `CURRENT_TIMESTAMP` = UTC naive. `2026-04-22 14:30:22`
- 신규 코드: `datetime.now(timezone.utc).isoformat()` = UTC aware. `2026-04-22T14:30:22.123456+00:00`

클라이언트가 뷰어 로컬 tz 로 정확히 변환하려면 **모든 DB 값이 aware** 여야 함.

**판별 규칙**
- `+` 또는 `Z` 꼬리 → 이미 aware → skip
- `T` 구분자 → Python isoformat → **KST 로 간주** → UTC 변환 후 `+00:00` 부착
- 공백 구분자 → SQLite CURRENT_TIMESTAMP → **UTC naive** → 그대로 `+00:00` 부착만

**대상 컬럼**: agents / relationships / conversations / events / memories / agent_facts / relationship_history / achievements / agent_personality / agent_appearance / agent_daily_life / agent_speech / agent_relationship_templates / agent_config / achievements 의 *_at · timestamp · last_active · valid_* 필드

**사용법**:
    python scripts/migrate_timestamps_to_utc.py                   # 모든 커뮤니티
    python scripts/migrate_timestamps_to_utc.py demo              # 특정 커뮤니티
    python scripts/migrate_timestamps_to_utc.py --dry-run         # 변경 미리보기

기본적으로 DB 파일을 먼저 백업함 (`community.db.pre-utc.backup`).
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMUNITIES_DIR = ROOT / "communities"

KST = timezone(timedelta(hours=9))
UTC = timezone.utc

# (table, column) 쌍 — INFORMATION_SCHEMA 없이 스키마 introspection 으로 자동 탐지하므로
# 이 리스트는 safe fallback 용. 실제로는 `PRAGMA table_info` 로 스캔해서 DATETIME 컬럼 전부 처리.
TS_COLUMN_HINTS = {"timestamp", "created_at", "updated_at", "last_active",
                   "unlocked_at", "completed_at", "valid_from", "valid_to",
                   "last_seen", "started_at", "completed", "last_used_at"}


def is_timestamp_column(col_type: str, col_name: str) -> bool:
    t = (col_type or "").upper()
    if "DATETIME" in t or "TIMESTAMP" in t or "DATE" in t:
        return True
    # 타입이 TEXT 인데 이름이 타임스탬프 힌트인 경우 (예: created_at TEXT)
    if col_name.lower() in TS_COLUMN_HINTS:
        return True
    return False


def convert_value(raw: str) -> tuple[str | None, str]:
    """raw 타임스탬프 문자열 → UTC aware ISO 반환. (None, 이유) 는 skip.
    반환: (new_value or None, reason)."""
    if raw is None:
        return None, "null"
    s = str(raw).strip()
    if not s:
        return None, "empty"
    # 이미 aware?
    if "+" in s[10:] or s.endswith("Z"):
        return None, "already_aware"

    try:
        # SQLite CURRENT_TIMESTAMP 형식: "2026-04-22 14:30:22" or "2026-04-22 14:30:22.123"
        # Python isoformat:                "2026-04-22T23:30:22" or "2026-04-22T23:30:22.123456"
        if "T" in s:
            dt = datetime.fromisoformat(s)
            # KST naive 로 간주
            dt = dt.replace(tzinfo=KST)
        else:
            # 공백 구분 → CURRENT_TIMESTAMP UTC naive
            dt = datetime.fromisoformat(s.replace(" ", "T"))
            dt = dt.replace(tzinfo=UTC)
    except Exception as e:
        return None, f"parse_fail: {e}"

    dt_utc = dt.astimezone(UTC)
    return dt_utc.isoformat(), "ok"


def migrate_db(db_path: Path, dry_run: bool = False) -> dict:
    """단일 DB 파일 마이그레이션. 변경 건수 리턴."""
    stats = {"tables_scanned": 0, "rows_updated": 0, "rows_skipped": 0, "errors": []}

    if not db_path.exists():
        stats["errors"].append(f"DB 없음: {db_path}")
        return stats

    if not dry_run:
        backup = db_path.with_suffix(db_path.suffix + ".pre-utc.backup")
        if not backup.exists():
            shutil.copy2(db_path, backup)
            print(f"  ✓ 백업 생성: {backup.name}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 테이블 목록
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]

    total_changes = 0

    for tbl in tables:
        try:
            cols = cur.execute(f"PRAGMA table_info({tbl})").fetchall()
        except Exception as e:
            stats["errors"].append(f"{tbl}: PRAGMA 실패 — {e}")
            continue

        ts_cols = [(c["name"], c["type"]) for c in cols if is_timestamp_column(c["type"], c["name"])]
        if not ts_cols:
            continue

        # PK 찾기 — UPDATE WHERE 용
        pk_cols = [c["name"] for c in cols if c["pk"]]
        if not pk_cols:
            # PK 없으면 rowid 로
            pk_cols = ["rowid"]

        stats["tables_scanned"] += 1

        for (col_name, col_type) in ts_cols:
            select_cols = ", ".join([f'"{p}"' for p in pk_cols] + [f'"{col_name}"'])
            try:
                rows = cur.execute(f"SELECT {select_cols} FROM {tbl} WHERE \"{col_name}\" IS NOT NULL").fetchall()
            except Exception as e:
                stats["errors"].append(f"{tbl}.{col_name}: SELECT 실패 — {e}")
                continue

            table_changes = 0
            for row in rows:
                pk_vals = tuple(row[p] for p in pk_cols)
                raw_val = row[col_name]
                new_val, reason = convert_value(raw_val)
                if new_val is None:
                    if reason not in ("already_aware", "null", "empty"):
                        stats["errors"].append(f"{tbl}.{col_name} PK={pk_vals}: {reason}  raw={raw_val!r}")
                    else:
                        stats["rows_skipped"] += 1
                    continue

                if dry_run:
                    table_changes += 1
                    continue

                where_clause = " AND ".join([f'"{p}" = ?' for p in pk_cols])
                try:
                    cur.execute(
                        f'UPDATE {tbl} SET "{col_name}" = ? WHERE {where_clause}',
                        (new_val, *pk_vals),
                    )
                    table_changes += 1
                except Exception as e:
                    stats["errors"].append(f"{tbl}.{col_name} PK={pk_vals} UPDATE 실패: {e}")

            if table_changes:
                total_changes += table_changes
                print(f"  {tbl}.{col_name}: {table_changes}건 {'변환 예정' if dry_run else '변환'}")

    stats["rows_updated"] = total_changes

    if not dry_run:
        conn.commit()
    conn.close()

    return stats


def main():
    ap = argparse.ArgumentParser(description="DB 타임스탬프 KST/UTC naive → UTC aware 마이그레이션")
    ap.add_argument("community", nargs="?", default=None,
                    help="특정 커뮤니티만 (생략 시 communities/ 아래 전체)")
    ap.add_argument("--dry-run", action="store_true", help="변경 미리보기")
    args = ap.parse_args()

    if args.community:
        targets = [COMMUNITIES_DIR / args.community]
    else:
        targets = [p for p in COMMUNITIES_DIR.iterdir() if p.is_dir()]

    grand = {"communities": 0, "rows_updated": 0, "rows_skipped": 0, "errors": []}

    for cdir in sorted(targets):
        db_path = cdir / "community.db"
        if not db_path.exists():
            continue
        print(f"\n=== {cdir.name} ===")
        stats = migrate_db(db_path, dry_run=args.dry_run)
        grand["communities"] += 1
        grand["rows_updated"] += stats["rows_updated"]
        grand["rows_skipped"] += stats["rows_skipped"]
        grand["errors"].extend([f"{cdir.name}: {e}" for e in stats["errors"]])
        print(f"  tables scanned: {stats['tables_scanned']} · rows updated: {stats['rows_updated']} · skipped: {stats['rows_skipped']}")
        if stats["errors"]:
            print(f"  ⚠ errors: {len(stats['errors'])}")
            for e in stats["errors"][:5]:
                print(f"    - {e}")

    print(f"\n===== 합계 =====")
    print(f"communities: {grand['communities']}")
    print(f"rows updated: {grand['rows_updated']}")
    print(f"rows skipped (already aware/null): {grand['rows_skipped']}")
    if grand["errors"]:
        print(f"errors: {len(grand['errors'])}")
        if len(grand["errors"]) > 10:
            print("(처음 10건만 표시)")
        for e in grand["errors"][:10]:
            print(f"  - {e}")
    if args.dry_run:
        print("\n** dry-run 모드 — 실제 변경 없음. --dry-run 없이 재실행 시 적용. **")


if __name__ == "__main__":
    main()
