"""기존 agent_facts 의 같은 의미 중복 fact 자동 정리 (canonical predicate 통일 + supersede).

각 (agent_id, subject) 그룹 안에서:
1. predicate 를 canonical form 으로 정규화
2. 같은 (agent_id, subject, canonical_pred) 인 valid 행 여러 개 → 가장 최근 1개만 keep,
   나머지 valid_to 세팅 (supersede)

Dry-run 기본. --apply 로 실제 변경.
Usage: GLIMI_COMMUNITY=test .venv/bin/python scripts/dedupe_agent_facts.py [--apply]
"""
import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("GLIMI_COMMUNITY", "test")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from community import db  # noqa: E402
from community.db import _canonicalize_predicate  # noqa: E402

APPLY = "--apply" in sys.argv


def main():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, agent_id, subject, predicate, object, valid_to "
        "FROM agent_facts WHERE valid_to IS NULL ORDER BY id ASC"
    ).fetchall()

    # 그룹: (agent_id, subject, canonical_pred) → [rows]
    groups: dict[tuple, list] = defaultdict(list)
    rename_count = 0
    for r in rows:
        canon = _canonicalize_predicate(r["predicate"])
        if canon != r["predicate"]:
            rename_count += 1
        key = (r["agent_id"], r["subject"], canon)
        groups[key].append(dict(r))

    print(f"전체 valid fact: {len(rows)}")
    print(f"predicate rename 대상 (canonical 로 변경): {rename_count}")

    duplicates_to_supersede = []
    for key, items in groups.items():
        if len(items) <= 1:
            continue
        # 최신 1개 keep, 나머지 supersede
        items.sort(key=lambda x: x["id"], reverse=True)
        keep = items[0]
        drop = items[1:]
        for d in drop:
            duplicates_to_supersede.append({
                "id": d["id"],
                "agent_id": d["agent_id"],
                "subject": d["subject"],
                "old_pred": d["predicate"],
                "canon": key[2],
                "object": d["object"],
                "kept": f"#{keep['id']} pred={keep['predicate']} obj={keep['object'][:30]}",
            })

    print(f"중복 supersede 대상: {len(duplicates_to_supersede)}")
    for d in duplicates_to_supersede[:20]:
        print(f"  #{d['id']} {d['agent_id'][:20]}/{d['subject']}/{d['old_pred']}→{d['canon']}: '{d['object'][:40]}' "
              f"(keep {d['kept']})")
    if len(duplicates_to_supersede) > 20:
        print(f"  ... 외 {len(duplicates_to_supersede) - 20}건")

    if not APPLY:
        print("\n--- DRY-RUN. --apply 로 실제 정리 ---")
        conn.close()
        return

    # APPLY: predicate canonical update + supersede
    for r in rows:
        canon = _canonicalize_predicate(r["predicate"])
        if canon != r["predicate"]:
            conn.execute("UPDATE agent_facts SET predicate=? WHERE id=?",
                         (canon, r["id"]))
    for d in duplicates_to_supersede:
        conn.execute("UPDATE agent_facts SET valid_to = CURRENT_TIMESTAMP WHERE id=?",
                     (d["id"],))
    conn.commit()
    conn.close()
    print(f"\n=== APPLY 완료 ===")
    print(f"  predicate 정규화: {rename_count}건")
    print(f"  중복 supersede: {len(duplicates_to_supersede)}건")


if __name__ == "__main__":
    main()
