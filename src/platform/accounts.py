"""계정 관리 + CLI.

사용법:
    python -m src.platform.accounts list
    python -m src.platform.accounts add <username> [--admin] [--password PW]
    python -m src.platform.accounts remove <username>
    python -m src.platform.accounts reset <username> --password PW
    python -m src.platform.accounts grant <username> <community_id>
    python -m src.platform.accounts revoke <username> <community_id>
    python -m src.platform.accounts bootstrap   # admin/1234 + test/1234 초기 생성
"""
import argparse
import hashlib
import os
import sys
from typing import Optional

from .db import conn, now_iso, init_db


# 비밀번호 해싱 — 단순 salted sha256. 1234 같은 약비번용으로 충분 (MVP).
_SALT = b"glimi-platform-v1"


def hash_password(password: str) -> str:
    return hashlib.sha256(_SALT + password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


# ── CRUD ─────────────────────────────────────────────────────────

def create_account(username: str, password: str, role: str = "user") -> int:
    assert role in ("admin", "user"), f"invalid role: {role}"
    with conn() as c:
        cur = c.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), role, now_iso()),
        )
        return cur.lastrowid


def delete_account(username: str) -> bool:
    with conn() as c:
        cur = c.execute("DELETE FROM users WHERE username = ?", (username,))
        return cur.rowcount > 0


def reset_password(username: str, password: str) -> bool:
    with conn() as c:
        cur = c.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_password(password), username),
        )
        return cur.rowcount > 0


def get_user(username: str) -> Optional[dict]:
    with conn() as c:
        row = c.execute(
            "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with conn() as c:
        row = c.execute(
            "SELECT id, username, password_hash, role, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def list_accounts() -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["communities"] = list_communities_for_user(d["id"])
            result.append(d)
        return result


# ── 커뮤니티 접근 권한 ───────────────────────────────────────────

def grant_community(user_id: int, community_id: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO user_communities (user_id, community_id, granted_at) VALUES (?, ?, ?)",
            (user_id, community_id, now_iso()),
        )


def revoke_community(user_id: int, community_id: str) -> bool:
    with conn() as c:
        cur = c.execute(
            "DELETE FROM user_communities WHERE user_id = ? AND community_id = ?",
            (user_id, community_id),
        )
        return cur.rowcount > 0


def list_communities_for_user(user_id: int) -> list[str]:
    with conn() as c:
        rows = c.execute(
            "SELECT community_id FROM user_communities WHERE user_id = ? ORDER BY community_id",
            (user_id,),
        ).fetchall()
        return [r["community_id"] for r in rows]


def user_can_access(user: dict, community_id: str) -> bool:
    """admin 은 모든 커뮤니티 접근 가능. 일반 유저는 user_communities 매핑으로만."""
    if user.get("role") == "admin":
        return True
    return community_id in list_communities_for_user(user["id"])


# ── 부트스트랩 ───────────────────────────────────────────────────

ADMIN_DEFAULT_COMMUNITIES = ["dev", "private", "demo", "qa"]


def bootstrap() -> None:
    """admin + user 계정 생성. 이미 있으면 skip.
    admin 에게 dev/private/demo/qa 커뮤니티 접근권 부여."""
    init_db()

    admin = get_user("admin")
    if admin is None:
        admin_id = create_account("admin", "rmfflal", role="admin")
        print(f"[bootstrap] 생성: admin (id={admin_id}) role=admin")
    else:
        admin_id = admin["id"]
        print(f"[bootstrap] skip: admin (id={admin_id}) 이미 존재")

    # admin 은 role=admin 이라 명시 grant 필요 없지만, 명시 기록해두면 UI 에서 보임
    for cid in ADMIN_DEFAULT_COMMUNITIES:
        grant_community(admin_id, cid)

    test = get_user("test")
    if test is None:
        test_id = create_account("test", "0000", role="user")
        print(f"[bootstrap] 생성: test (id={test_id}) role=user")
    else:
        print(f"[bootstrap] skip: test (id={test['id']}) 이미 존재")


# ── CLI ─────────────────────────────────────────────────────────

def _cli() -> None:
    ap = argparse.ArgumentParser(prog="src.platform.accounts")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="모든 계정 나열")
    sub.add_parser("bootstrap", help="admin/1234 + test/1234 초기 생성")

    p_add = sub.add_parser("add", help="계정 생성")
    p_add.add_argument("username")
    p_add.add_argument("--password", default="1234")
    p_add.add_argument("--admin", action="store_true")

    p_rm = sub.add_parser("remove", help="계정 삭제")
    p_rm.add_argument("username")

    p_reset = sub.add_parser("reset", help="비밀번호 초기화")
    p_reset.add_argument("username")
    p_reset.add_argument("--password", required=True)

    p_grant = sub.add_parser("grant", help="커뮤니티 접근 권한 부여")
    p_grant.add_argument("username")
    p_grant.add_argument("community_id")

    p_revoke = sub.add_parser("revoke", help="커뮤니티 접근 권한 회수")
    p_revoke.add_argument("username")
    p_revoke.add_argument("community_id")

    args = ap.parse_args()

    if args.cmd == "list":
        for u in list_accounts():
            communities = ", ".join(u["communities"]) or "(none)"
            role_badge = "admin" if u["role"] == "admin" else "user "
            print(f"  [{u['id']:>3}] {role_badge} {u['username']:<20} communities: {communities}")
        if not list_accounts():
            print("  (계정 없음 — `python -m src.platform.accounts bootstrap` 로 기본 계정 생성)")

    elif args.cmd == "bootstrap":
        bootstrap()

    elif args.cmd == "add":
        if get_user(args.username):
            print(f"이미 존재: {args.username}")
            sys.exit(1)
        role = "admin" if args.admin else "user"
        uid = create_account(args.username, args.password, role=role)
        print(f"생성: {args.username} (id={uid}) role={role} password={args.password}")

    elif args.cmd == "remove":
        if delete_account(args.username):
            print(f"삭제: {args.username}")
        else:
            print(f"없음: {args.username}")
            sys.exit(1)

    elif args.cmd == "reset":
        if reset_password(args.username, args.password):
            print(f"비밀번호 초기화: {args.username} → {args.password}")
        else:
            print(f"없음: {args.username}")
            sys.exit(1)

    elif args.cmd == "grant":
        user = get_user(args.username)
        if not user:
            print(f"없음: {args.username}")
            sys.exit(1)
        grant_community(user["id"], args.community_id)
        print(f"부여: {args.username} → {args.community_id}")

    elif args.cmd == "revoke":
        user = get_user(args.username)
        if not user:
            print(f"없음: {args.username}")
            sys.exit(1)
        if revoke_community(user["id"], args.community_id):
            print(f"회수: {args.username} ↛ {args.community_id}")
        else:
            print(f"권한 없었음: {args.username} ↛ {args.community_id}")


if __name__ == "__main__":
    _cli()
