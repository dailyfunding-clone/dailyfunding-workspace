#!/usr/bin/env python3
"""투자 경합·멱등 동시성 검증 (k6 시나리오의 Python 구현 — 즉시 실행용).

N명이 remaining < N*amount 상품에 동시 투자:
  - oversell 0건 (raised <= target)
  - 성공 수 == target // amount
  - 동일 Idempotency-Key 재시도 → 같은 investment_id

실행: python3 scripts/race-invest.py [N] [amount]
"""

import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

API = os.environ.get("API_BASE", "http://localhost:8000")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
AMOUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 100_000


def req(method, path, session=None, idem=None, reauth=None, **kw):
    headers = {"Content-Type": "application/json"}
    if idem:
        headers["Idempotency-Key"] = idem
    if reauth:
        headers["X-Reauth-Token"] = reauth
    s = session or requests
    return s.request(method, f"{API}{path}", headers=headers, **kw)


def login(email, password):
    s = requests.Session()
    r = req("POST", "/api/auth/login", s, json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code}"
    return s


def make_user(i):
    email = f"race-{uuid.uuid4().hex[:8]}@test.com"
    password = "Test1234!"
    name = f"경합{i:02d}"
    req(
        "POST",
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
            "name": name,
            "agreements": [
                {"term": t, "agreed": True}
                for t in ("service", "investment", "electronic_finance", "privacy", "credit_info")
            ],
        },
    )
    sess = login(email, password)
    req(
        "POST",
        "/api/auth/identity/verify",
        sess,
        json={"carrier": "SKT", "name": name, "birth": "19950101", "phone": f"010{i + 10**7:08d}"},
    )
    req(
        "POST",
        "/api/suitability-test",
        sess,
        json={"answers": [{"seq": s, "choice": c} for s, c in zip(range(1, 7), "XOOXOO")]},
    )
    r = req(
        "POST",
        "/api/deposit/notify-intent",
        sess,
        idem=uuid.uuid4().hex,
        json={"sender_name": name, "amount": AMOUNT * 2},
    )
    req("POST", "/mockbank/deposits/execute", json={"intent_id": r.json()["intent_id"]})
    r = req("POST", "/api/auth/reauth", sess, json={"password": password})
    return {"sess": sess, "reauth": r.json()["reauth_token"], "idem": uuid.uuid4().hex}


def attempt(user, product_id):
    kw = dict(
        idem=user["idem"],
        reauth=user["reauth"],
        json={"product_id": product_id, "amount": AMOUNT, "confirm": "네"},
    )
    r = req("POST", "/api/investments", user["sess"], **kw)
    replay = req("POST", "/api/investments", user["sess"], **kw)
    return r, replay


admin = login("admin@demo.local", "Admin1234!")
slots = N - 2  # 남는 자리보다 많은 경쟁자 → 초과 모집 시도 유발
target = slots * AMOUNT
r = req(
    "POST",
    "/api/admin/products",
    admin,
    json={
        "name": f"경합 테스트 {uuid.uuid4().hex[:6]}",
        "type": "scf",
        "annual_rate": "9.00",
        "term_months": 1,
        "target_amount": target,
        "repay_type": "bullet",
        "borrower_id": f"brw-{uuid.uuid4().hex[:8]}",
    },
)
assert r.status_code == 201, r.text
pid = r.json()["id"]
r = req("PATCH", f"/api/admin/products/{pid}/status", admin, json={"status": "recruiting"})
assert r.status_code == 200

print(f"product {pid}: target={target:,} slots={slots} racers={N}")

print(f"preparing {N} users...", flush=True)
with ThreadPoolExecutor(N) as ex:
    users = list(ex.map(make_user, range(N)))

print("racing investments...", flush=True)
with ThreadPoolExecutor(N) as ex:
    results = list(ex.map(lambda u: attempt(u, pid), users))

created = [r for r, _ in results if r.status_code == 201]
conflicts = [r for r, _ in results if r.status_code == 409]
id_mismatch = [
    (r, rp)
    for r, rp in results
    if r.status_code == 201
    and rp.status_code in (200, 201)
    and rp.json().get("investment_id") != r.json().get("investment_id")
]

p = req("GET", f"/api/products/{pid}").json()
raised = p["raised_amount"]

print(f"created={len(created)} conflicts={len(conflicts)} raised={raised:,} target={target:,}")
print(f"idempotent replay mismatches={len(id_mismatch)}")

assert len(created) == slots, f"expected {slots} winners, got {len(created)}"
assert raised <= target, "OVERSELL"
assert not id_mismatch, "idempotency replay produced different investment"
print("RACE TEST PASS — oversell 0, idempotent replays consistent")
