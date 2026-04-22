"""agent_facts 테이블의 기존 쓰레기 정리 + predicate 정규화.

대상:
  1. 추상/집합/가상 subject ('새_멤버', '이 커뮤니티', '멤버들' 등) → 해당 fact invalidate
  2. 실존 인물 아닌 subject → invalidate
  3. 일시 상태만 담긴 object ('오랜만', '지금') → invalidate
  4. predicate 정규화 (alias → canonical) — UPDATE in-place
  5. 자기 자신 fact 가 profile 과 중복인 경우 → invalidate

Dry-run (기본) 으로 삭제 건수만 출력. --apply 주면 실제 적용.

Usage:
  GLIMI_COMMUNITY=qa .venv/bin/python scripts/cleanup_memory.py
  GLIMI_COMMUNITY=qa .venv/bin/python scripts/cleanup_memory.py --apply
"""
import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.core import memory as mem  # noqa: E402
from src import db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 변경 적용 (기본은 dry-run)")
    args = ap.parse_args()

    community_id = os.environ.get("GLIMI_COMMUNITY", "(unset)")
    print(f"community: {community_id}")
    print(f"db: {db._get_db_path()}")
    print(f"mode: {'APPLY' if args.apply else 'dry-run'}")
    print()

    allowed = mem._known_real_subjects()
    print(f"allowed subjects ({len(allowed)}): {sorted(allowed)}")

    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, agent_id, subject, predicate, object FROM agent_facts WHERE valid_to IS NULL"
    ).fetchall()

    drops_abstract: list[tuple] = []
    drops_unknown: list[tuple] = []
    drops_transient: list[tuple] = []
    drops_profile_dup: list[tuple] = []
    pred_updates: list[tuple] = []

    for r in rows:
        fid = r["id"]
        agent_id = r["agent_id"]
        subj = (r["subject"] or "").strip()
        pred = (r["predicate"] or "").strip()
        obj = (r["object"] or "").strip()

        # 1. 추상/메타 subject
        if mem._is_meta_subject(subj):
            drops_abstract.append((fid, agent_id, subj, pred, obj))
            continue
        # 2. 실존 인물 아닌 subject
        norm_subj = mem._normalize_entity(subj)
        if allowed and norm_subj not in allowed:
            drops_unknown.append((fid, agent_id, norm_subj, pred, obj))
            continue
        # 3. 일시 상태 object
        if mem._is_transient_object(obj):
            drops_transient.append((fid, agent_id, norm_subj, pred, obj))
            continue
        # 4. predicate 정규화
        canon = mem._canonical_predicate(pred)
        if canon != pred:
            pred_updates.append((fid, pred, canon))
        # 5. 자기 자신 profile 중복
        try:
            from src.core.profile import load_profile
            prof = load_profile(agent_id)
            if prof and prof.get("name") == norm_subj:
                if mem._profile_has_value(agent_id, canon, obj):
                    drops_profile_dup.append((fid, agent_id, norm_subj, canon, obj))
        except Exception:
            pass

    print("\n── dry-run stats ──")
    print(f"  abstract subject drops: {len(drops_abstract)}")
    for x in drops_abstract:
        print(f"    - id={x[0]}  {x[2]} | {x[3]} | {x[4]}")
    print(f"  unknown-person subject drops: {len(drops_unknown)}")
    for x in drops_unknown:
        print(f"    - id={x[0]}  {x[2]} | {x[3]} | {x[4]}")
    print(f"  transient object drops: {len(drops_transient)}")
    for x in drops_transient:
        print(f"    - id={x[0]}  {x[2]} | {x[3]} | {x[4]}")
    print(f"  self-profile duplicate drops: {len(drops_profile_dup)}")
    for x in drops_profile_dup:
        print(f"    - id={x[0]}  {x[2]} | {x[3]} | {x[4]}")
    print(f"  predicate updates: {len(pred_updates)}")
    # predicate 변경 요약 (빈도순)
    from collections import Counter
    cnt = Counter((old, new) for _, old, new in pred_updates)
    for (old, new), n in cnt.most_common():
        print(f"    - '{old}' → '{new}'  ({n}회)")

    total_drops = (len(drops_abstract) + len(drops_unknown)
                   + len(drops_transient) + len(drops_profile_dup))
    print(f"\nTOTAL: {total_drops} drops, {len(pred_updates)} predicate renames")

    if not args.apply:
        print("\n(dry-run — pass --apply to commit changes)")
        conn.close()
        return

    # 적용
    print("\n── applying ──")
    drop_ids = set()
    for lst in (drops_abstract, drops_unknown, drops_transient, drops_profile_dup):
        for x in lst:
            drop_ids.add(x[0])
    if drop_ids:
        conn.executemany(
            "UPDATE agent_facts SET valid_to = CURRENT_TIMESTAMP WHERE id = ?",
            [(i,) for i in drop_ids],
        )
        print(f"  invalidated {len(drop_ids)} facts")
    # predicate 업데이트 — drop 된 것 제외
    pred_apply = [(canon, fid) for fid, old, canon in pred_updates if fid not in drop_ids]
    if pred_apply:
        conn.executemany(
            "UPDATE agent_facts SET predicate = ? WHERE id = ?",
            pred_apply,
        )
        print(f"  renamed {len(pred_apply)} predicates")

    # rename 후 (agent_id, subject, predicate) 당 여러 valid row 중복 → 최신(id DESC) 만 남김
    conn.commit()
    dup_rows = conn.execute(
        """SELECT agent_id, subject, predicate, COUNT(*) AS c
           FROM agent_facts WHERE valid_to IS NULL
           GROUP BY agent_id, subject, predicate
           HAVING c > 1"""
    ).fetchall()
    collapsed = 0
    for d in dup_rows:
        rows = conn.execute(
            """SELECT id FROM agent_facts
               WHERE agent_id=? AND subject=? AND predicate=? AND valid_to IS NULL
               ORDER BY id DESC""",
            (d["agent_id"], d["subject"], d["predicate"]),
        ).fetchall()
        # 첫(최신) 은 유지, 나머지 invalidate
        to_close = [r["id"] for r in rows[1:]]
        if to_close:
            conn.executemany(
                "UPDATE agent_facts SET valid_to = CURRENT_TIMESTAMP WHERE id = ?",
                [(i,) for i in to_close],
            )
            collapsed += len(to_close)
    if collapsed:
        print(f"  collapsed {collapsed} duplicate rows after predicate rename")
    conn.commit()
    conn.close()
    print("done.")


if __name__ == "__main__":
    main()
