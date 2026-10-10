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

const invested = new Counter("invest_created");
const idemReplays = new Counter("idempotent_replay_same_id");
const idemMismatch = new Counter("idempotent_replay_mismatch");

const json = (cookie, csrf) => ({
  headers: {
    "Content-Type": "application/json",
    ...(cookie ? { Cookie: cookie } : {}),
    ...(csrf ? { "X-CSRF-Token": csrf } : {}),
  },
});

const login = (email, password) => {
  const r = http.post(`${API}/api/auth/login`, JSON.stringify({ email, password }), json());
  if (r.status !== 200) fail(`login ${email}: ${r.status}`);
  const parts = [];
  let csrf = "";
  for (const name of ["access", "refresh", "csrf"]) {
    const c = r.cookies[name];
    if (c && c[0]) {
      parts.push(`${name}=${c[0].value}`);
      if (name === "csrf") csrf = c[0].value;
    }
  }
  return { cookie: parts.join("; "), csrf };
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
  const productId = Number(__ENV.PRODUCT_ID);
  const product = http.get(`${API}/api/products/${productId}`);
  if (product.status !== 200) fail(`product fetch: ${product.status}`);
  const remaining = product.json("remaining_amount") ?? product.json("target_amount");

  const users = [];
  for (let i = 0; i < VUS; i++) {
    const email = `k6-${Date.now()}-${i}@test.com`;
    const password = "Test1234!";
    const name = `케이유저${i}`;
    const signup = http.post(
      `${API}/api/auth/signup`,
      JSON.stringify({
        email,
        password,
        name,
        agreements: ["service", "investment", "electronic_finance", "privacy", "credit_info"].map(
          (t) => ({ term: t, agreed: true })
        ),
      }),
      json()
    );
    if (signup.status !== 201) fail(`signup ${email}: ${signup.status} ${signup.body}`);
    const u = login(email, password);
    const auth = json(u.cookie, u.csrf);
    const ident = http.post(
      `${API}/api/auth/identity/verify`,
      JSON.stringify({ carrier: "SKT", name, birth: "19950101", phone: `010${String(10000000 + i)}` }),
      auth
    );
    if (ident.status !== 200 || !ident.json("verified")) {
      fail(`identity ${email}: ${ident.status} ${ident.body}`);
    }
    const answers = [1, 2, 3, 4, 5, 6].map((s, k) => ({ seq: s, choice: "XOOXOO"[k] }));
    const suit = http.post(`${API}/api/suitability-test`, JSON.stringify({ answers }), auth);
    if (suit.status !== 200 || !suit.json("passed")) {
      fail(`suitability ${email}: ${suit.status} ${suit.body}`);
    }
    const intent = http.post(
      `${API}/api/deposit/notify-intent`,
      JSON.stringify({ sender_name: name, amount: AMOUNT * 2 }),
      { headers: { ...auth.headers, "Idempotency-Key": uuidv4() } }
    );
    if (![200, 201, 202].includes(intent.status)) {
      fail(`intent ${email}: ${intent.status} ${intent.body}`);
    }
    const dep = http.post(
      `${API}/mockbank/deposits/execute`,
      JSON.stringify({ intent_id: intent.json("intent_id") }),
      json()
    );
    if (dep.status !== 200) fail(`deposit execute ${email}: ${dep.status} ${dep.body}`);
    const reauth = http.post(`${API}/api/auth/reauth`, JSON.stringify({ password }), auth);
    if (reauth.status !== 200 || !reauth.json("reauth_token")) {
      fail(`reauth ${email}: ${reauth.status} ${reauth.body}`);
    }
    users.push({ token: u.cookie, csrf: u.csrf, reauth: reauth.json("reauth_token"), idem: uuidv4() });
  }
  return { users, productId, remaining };
}

export default function (data) {
  const u = data.users[exec.vu.idInTest - 1];
  const body = JSON.stringify({ product_id: data.productId, amount: AMOUNT, confirm: "네" });
  const headers = {
    "Content-Type": "application/json",
    Cookie: u.token,
    "X-CSRF-Token": u.csrf,
    "Idempotency-Key": u.idem,
    "X-Reauth-Token": u.reauth,
  };

  const r1 = http.post(`${API}/api/investments`, body, { headers });
  // 201 성공과 409 경합 탈락 모두 기대 결과 — 그 외만 실패로 집계
  check(r1, { "created or expected conflict": (r) => [201, 409].includes(r.status) });
  if (r1.status === 201) invested.add(1);

  // 멱등 재시도: 같은 키 → 동일 investment_id
  const r2 = http.post(`${API}/api/investments`, body, { headers });
  if (r1.status === 201 && [200, 201].includes(r2.status)) {
    if (r2.json("investment_id") === r1.json("investment_id")) {
      idemReplays.add(1);
    } else {
      idemMismatch.add(1);
    }
  }
}

export function teardown(data) {
  const r = http.get(`${API}/api/products/${data.productId}`);
  if (r.status !== 200) fail(`teardown product fetch: ${r.status}`);
  const raised = r.json("raised_amount");
  const target = r.json("target_amount");
  if (raised > target) fail(`oversell: raised=${raised} target=${target}`);
}
