#!/usr/bin/env python3
"""전체 라이프사이클 E2E: 가입 → 인증 → 적합성 → 계좌연결 → 충전 →
상품생성/모집 → 투자 → 실행 → 상환 → 출금.

대상: http://localhost:8000 (환경변수 API_BASE로 변경 가능).
실행: python3 scripts/e2e-lifecycle.py
"""

import os
import sys
import time
import uuid
from datetime import date, timedelta

import requests

API = os.environ.get("API_BASE", "http://localhost:8000")
ADMIN = ("admin@demo.local", "Admin1234!")

step = 0


def ok(cond, label, detail=""):
    global step
    step += 1
    status = "PASS" if cond else "FAIL"
    print(f"[{step:02d}] {status} {label} {detail}")
    if not cond:
        sys.exit(1)


def req(method, path, session=None, **kw):
    headers = kw.pop("headers", {})
    headers.setdefault("Content-Type", "application/json")
    s = session or requests
    if session is not None and method.upper() not in ("GET", "HEAD", "OPTIONS"):
        csrf = session.cookies.get("csrf")
        if csrf:
            headers.setdefault("X-CSRF-Token", csrf)
    return s.request(method, f"{API}{path}", headers=headers, **kw)


def login(email, password):
    s = requests.Session()
    r = req("POST", "/api/auth/login", s, json={"email": email, "password": password})
    ok(r.status_code == 200, f"login {email}", f"{r.status_code}")
    return s


email = f"e2e-{uuid.uuid4().hex[:8]}@test.com"
password = "Test1234!"
name = "이이투이"

# 1. 회원가입 + 본인인증
r = req(
    "POST",
    "/api/auth/signup",
    json={
        "email": email,
        "password": password,
        "name": name,
        "agreements": [
            {"term": t, "agreed": True}
            for t in (
                "service",
                "investment",
                "electronic_finance",
                "privacy",
                "credit_info",
            )
        ],
    },
)
ok(r.status_code == 201, "signup", f"{r.status_code} {r.text[:120]}")

sess = login(email, password)

r = req(
    "POST",
    "/api/auth/identity/verify",
    sess,
    json={
        "carrier": "SKT",
        "name": name,
        "birth": "19950101",
        "phone": f"010{uuid.uuid4().int % 10**8:08d}",
    },
)
ok(r.status_code == 200 and r.json().get("verified"), "identity verify", r.text[:100])

# 2. 적합성 테스트 (정답: X O O X O O)
answers = [{"seq": s, "choice": c} for s, c in zip(range(1, 7), "XOOXOO")]
r = req("POST", "/api/suitability-test", sess, json={"answers": answers})
ok(r.status_code == 200 and r.json().get("passed"), "suitability pass", r.text[:100])

# 3. 연결계좌 (reauth 게이트)
r = req("POST", "/api/auth/reauth", sess, json={"password": password})
ok(r.status_code == 200, "reauth", f"{r.status_code}")
reauth = r.json()["reauth_token"]

r = req(
    "PUT",
    "/api/deposit/linked-account",
    sess,
    json={"bank_name": "국민은행", "account_no": "12345678901234", "holder": name},
    headers={"X-Reauth-Token": reauth},
)
ok(r.status_code in (200, 201), "linked account", f"{r.status_code} {r.text[:100]}")

# 4. 충전: 입금의사 → mockbank 실행 → 잔액 확인
r = req(
    "POST",
    "/api/deposit/notify-intent",
    sess,
    json={"sender_name": name, "amount": 1_000_000},
    headers={"Idempotency-Key": uuid.uuid4().hex},
)
ok(r.status_code in (200, 201, 202), "notify-intent", f"{r.status_code} {r.text[:120]}")
intent_id = r.json().get("intent_id") or r.json().get("id")

r = req(
    "POST",
    "/mockbank/deposits/execute",
    json={"intent_id": intent_id},
)
ok(r.status_code == 200 and r.json().get("delivered"), "deposit webhook", r.text[:120])

r = req("GET", "/api/deposit/account", sess)
balance = r.json().get("deposit", 0)
ok(r.status_code == 200 and balance >= 1_000_000, "deposit balance", f"balance={balance}")

# 5. 관리자: 상품 생성 → 모집오픈
admin = login(*ADMIN)
target = 500_000
r = req(
    "POST",
    "/api/admin/products",
    admin,
    json={
        "name": f"E2E 상품 {uuid.uuid4().hex[:6]}",
        "type": "scf",
        "annual_rate": "10.00",
        "term_months": 1,
        "target_amount": target,
        "repay_type": "bullet",
        "borrower_id": f"brw-{uuid.uuid4().hex[:8]}",
    },
)
ok(r.status_code == 201, "admin product create", f"{r.status_code} {r.text[:120]}")
pid = r.json()["id"]

r = req("PATCH", f"/api/admin/products/{pid}/status", admin, json={"status": "recruiting"})
ok(r.status_code == 200 and r.json().get("status") == "recruiting", "product open", r.text[:100])

# 6. 투자 (전액 → 자동 recruited, reauth 게이트)
r = req("POST", "/api/auth/reauth", sess, json={"password": password})
ok(r.status_code == 200, "reauth for invest", f"{r.status_code}")
reauth = r.json()["reauth_token"]

r = req(
    "POST",
    "/api/investments",
    sess,
    json={"product_id": pid, "amount": target, "confirm": "네"},
    headers={"Idempotency-Key": uuid.uuid4().hex, "X-Reauth-Token": reauth},
)
ok(r.status_code == 201, "invest", f"{r.status_code} {r.text[:150]}")
inv_id = r.json()["investment_id"]

r = req("GET", f"/api/products/{pid}", sess)
ok(r.status_code == 200 and r.json().get("status") == "recruited", "auto-recruited", r.json().get("status"))

# 7. 대출 실행 → 상환 스케줄 확정
r = req("POST", f"/api/admin/products/{pid}/execute", admin)
ok(r.status_code == 200, "execute loan", f"{r.status_code} {r.text[:120]}")

r = req("GET", f"/api/investments/{inv_id}", sess)
sched = r.json().get("schedule", [])
ok(r.status_code == 200 and sched, "schedule exists", f"rows={len(sched)}")
due = sched[0].get("due_date") or sched[0].get("pay_date")
print(f"     due_date={due}")

# 8. 시간 진행 + 상환 배치
paid, detail = 0, ""
for _ in range(40):
    r = req("POST", "/api/admin/batch/repay?date=" + str(due), admin)
    if r.status_code == 200 and r.json().get("paid", 0) > 0:
        paid, detail = r.json()["paid"], r.text[:150]
        break
    r2 = req("POST", "/api/admin/time/advance", admin, json={"date": str(due)})
    if r2.status_code == 200:
        paid, detail = r2.json().get("repay", {}).get("paid", 0), r2.text[:150]
        break
    due = (date.fromisoformat(due) + timedelta(days=1)).isoformat()
ok(paid >= 1, "repay batch", detail)

# 9. 상환 후 잔액 → 전액 출금
r = req("GET", "/api/deposit/account", sess)
balance = r.json().get("deposit", 0)
ok(balance > 500_000, "repaid balance", f"balance={balance}")

r = req("POST", "/api/auth/reauth", sess, json={"password": password})
reauth = r.json()["reauth_token"]
r = req(
    "POST",
    "/api/deposit/withdraw",
    sess,
    json={"all": True},
    headers={"X-Reauth-Token": reauth, "Idempotency-Key": uuid.uuid4().hex},
)
ok(r.status_code in (200, 201, 202), "withdraw request", f"{r.status_code} {r.text[:120]}")
withdrawal_id = r.json()["withdrawal_id"]

# 출금 이체 실행 (mockbank)
r = req(
    "POST",
    "/mockbank/transfers/execute",
    json={"withdrawal_id": withdrawal_id, "success": True},
)
ok(r.status_code == 200 and r.json().get("delivered"), "transfer execute", r.text[:120])

balance = None
for _ in range(20):
    r = req("GET", "/api/deposit/account", sess)
    balance = r.json().get("deposit", 0)
    if balance < 1_000_000:
        break
    time.sleep(0.5)
ok(balance is not None and balance < 1_000_000, "final balance", f"balance={balance}")

print(f"\nALL PASS — lifecycle e2e ({step} steps)")
