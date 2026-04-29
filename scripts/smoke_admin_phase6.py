"""
Admin Phase 6 스모크: 감사 로그 IP/UA, 조회 API, /admin/audit, 로그아웃 쿠키.
실행: cd /home/flairy/v4 && PYTHONPATH=. python scripts/smoke_admin_phase6.py
"""
from __future__ import annotations

import os
import sys
import uuid

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "." not in sys.path:
    sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.security import hash_password
from app.database import (
    engine,
    ensure_admin_action_logs_table,
    ensure_admin_users_table,
    ensure_users_table_addons,
)
from app.main import app

ADMIN_USER = "smoke_p6_admin"
ADMIN_PASS = "smoke_p6_secret"
USER_EMAIL = "smoke_p6_user@test.local"


def main() -> None:
    ensure_admin_users_table()
    ensure_users_table_addons()
    ensure_admin_action_logs_table()

    admin_id = uuid.uuid4()
    user_id = uuid.uuid4()
    hp = hash_password(ADMIN_PASS)

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO admin_users (id, username, hashed_password, role)
                VALUES (:id, :username, :hp, 'super_admin')
                ON CONFLICT (username) DO UPDATE SET
                    hashed_password = EXCLUDED.hashed_password,
                    id = admin_users.id
            """),
            {"id": admin_id, "username": ADMIN_USER, "hp": hp},
        )
        row = conn.execute(
            text("SELECT id::text FROM admin_users WHERE username = :u"),
            {"u": ADMIN_USER},
        ).first()
        assert row
        admin_id = uuid.UUID(row[0])

        conn.execute(
            text("""
                INSERT INTO users (id, email, hashed_password, provider, is_active)
                VALUES (:id, :email, :hp, 'local', true)
                ON CONFLICT (email) DO NOTHING
            """),
            {"id": user_id, "email": USER_EMAIL, "hp": hp},
        )
        ur = conn.execute(
            text("SELECT id::text FROM users WHERE email = :e"),
            {"e": USER_EMAIL},
        ).first()
        assert ur
        user_id = uuid.UUID(ur[0])

    client = TestClient(app)

    r = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    cookies = r.cookies

    r2 = client.patch(
        f"/api/admin/users/{user_id}/status",
        json={"is_active": False},
        cookies=cookies,
        headers={"user-agent": "SmokeTestAgent/1.0"},
    )
    assert r2.status_code == 200, r2.text

    r3 = client.get(
        "/api/admin/audit-logs?page=1&page_size=10",
        cookies=cookies,
    )
    assert r3.status_code == 200, r3.text
    data = r3.json()
    items = data.get("items") or []
    assert items, "감사 로그가 비어 있음"
    last = items[0]
    assert last.get("action_type") == "BAN_USER"
    assert last.get("ip_address"), "ip_address 누락"
    assert last.get("user_agent"), "user_agent 누락"
    assert isinstance(last.get("details"), dict)

    r4 = client.get("/admin/audit", cookies=cookies, follow_redirects=False)
    assert r4.status_code == 200
    assert "감사 로그".encode("utf-8") in r4.content

    r5 = client.get("/admin/logout", cookies=cookies, follow_redirects=False)
    assert r5.status_code == 302
    assert r5.headers.get("location", "").endswith("/admin/login")

    # 테스트 유저 다시 활성화 (운영 DB 오염 방지)
    r6 = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        follow_redirects=False,
    )
    assert r6.status_code == 302
    r7 = client.patch(
        f"/api/admin/users/{user_id}/status",
        json={"is_active": True},
        cookies=r6.cookies,
    )
    assert r7.status_code == 200, r7.text

    print("smoke_admin_phase6: OK")


if __name__ == "__main__":
    main()
