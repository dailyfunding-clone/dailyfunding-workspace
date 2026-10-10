// k6 투자 경합·멱등 시나리오 (tech-stack 3.절: 초과 모집 0건 측정)
//
// 사전 조건:
//   1) 모집중 상품 PRODUCT_ID (remaining < VUS*AMOUNT 여야 경합 발생)
//   2) 사전 생성 유저들이 예치금 보유 — setup()에서 유저 생성+충전 자동화
//
// 실행: k6 run scripts/load-invest.k6.js
//   -e API_BASE=http://localhost:8000 -e PRODUCT_ID=1 -e VUS=20 -e AMOUNT=100000
import http from "k6/http";
import { check, fail } from "k6";
import { Counter } from "k6/metrics";
import exec from "k6/execution";

const uuidv4 = () => crypto.randomUUID();

const API = __ENV.API_BASE || "http://localhost:8000";
const VUS = Number(__ENV.VUS || 20);
const AMOUNT = Number(__ENV.AMOUNT || 100000);
const ADMIN = { email: "admin@demo.local", password: "Admin1234!" };

const invested = new Counter("invest_created");
const overSold = new Counter("oversell_detected");
const idemReplays = new Counter("idempotent_replay_same_id");

const json = (t) => ({
  headers: {
    "Content-Type": "application/json",
    ...(t ? { Authorization: `Bearer ${t}` } : {}),
  },
});

const login = (email, password) => {
  const r = http.post(`${API}/api/auth/login`, JSON.stringify({ email, password }), json(null, ""));
  if (r.status !== 200) fail(`login ${email}: ${r.status}`);
  return r.json("access_token");
};

export const options = {
  scenarios: {
    race: {
      executor: "per-vu-iterations",
      vus: VUS,
      iterations: 1,
      maxDuration: "2m",
    },
  },
};

export function setup() {
  const admin = login(ADMIN.email, ADMIN.password);
  const productId = Number(__ENV.PRODUCT_ID);
  const product = http.get(`${API}/api/products/${productId}`);
  if (product.status !== 200) fail(`product fetch: ${product.status}`);
  const target = product.json("target_amount");
  const remaining = product.json("remaining_amount") ?? target;

  const users = [];
  for (let i = 0; i < VUS; i++) {
    const email = `k6-${Date.now()}-${i}@test.com`;
    http.post(
      `${API}/api/auth/signup`,
      JSON.stringify({
        email,
        password: "Test1234!",
        name: `케이유저${i}`,
        agreements: ["service", "investment", "electronic_finance", "privacy", "credit_info"].map(
          (t) => ({ term: t, agreed: true })
        ),
      }),
      json(null, "")
    );
    const t = login(email, "Test1234!");
    http.post(
      `${API}/api/auth/identity/verify`,
      JSON.stringify({ carrier: "SKT", name: `케이유저${i}`, birth: "19950101", phone: `010${String(10000000 + i)}` }),
      json(t, "")
    );
    const answers = [1, 2, 3, 4, 5, 6].map((s, k) => ({ seq: s, choice: "XOOXOO"[k] }));
    http.post(`${API}/api/suitability-test`, JSON.stringify({ answers }), json(t, ""));
    const intent = http.post(
      `${API}/api/deposit/notify-intent`,
      JSON.stringify({ sender_name: `케이유저${i}`, amount: AMOUNT * 2 }),
      { headers: { "Content-Type": "application/json", Authorization: `Bearer ${t}`, "Idempotency-Key": uuidv4() } }
    );
    http.post(`${API}/mockbank/deposits/execute`, JSON.stringify({ intent_id: intent.json("intent_id") }), json(null, ""));
    const reauth = http.post(
      `${API}/api/auth/reauth`,
      JSON.stringify({ password: "Test1234!" }),
      json(t, "")
    );
    users.push({ token: t, reauth: reauth.json("reauth_token"), idem: uuidv4() });
  }
  return { users, productId, remaining };
}

export default function (data) {
  const u = data.users[exec.vu.idInTest - 1];
  const body = JSON.stringify({ product_id: data.productId, amount: AMOUNT, confirm: "네" });
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${u.token}`,
    "Idempotency-Key": u.idem,
    "X-Reauth-Token": u.reauth,
  };

  const r1 = http.post(`${API}/api/investments`, body, { headers });
  if (check(r1, { "created": (r) => r.status === 201 })) invested.add(1);
  if (r1.status === 201 && r1.json("amount") > data.remaining) overSold.add(1);

  // 멱등 재시도: 같은 키 → 동일 investment_id
  const r2 = http.post(`${API}/api/investments`, body, { headers });
  if (r1.status === 201 && [200, 201].includes(r2.status)) {
    if (r2.json("investment_id") === r1.json("investment_id")) {
      idemReplays.add(1);
    } else {
      overSold.add(1);
    }
  }
}
