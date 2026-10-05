# API 명세서 — 데일리펀딩 클론

- 문서 버전: v2.0 · 작성일: 2026-10-01
- 기준 문서: `PRD.md` · `feature-spec.md` · `tech-stack.md` · `../dailyfunding-be/docs/project-plan.md`
- 정본 정책: 이 문서는 설계 명세다. 구현 후에는 drf-spectacular가 생성하는 `schema.json`이 정본이 되며, 이 문서와 불일치 시 스키마를 기준으로 한다.

---

## 1. 공통 규약

### 1.1 기본

| 항목 | 규약 |
|---|---|
| Base URL | `{API}/api` |
| 인증 | JWT access+refresh, httpOnly 쿠키. `access` 15분, `refresh` 14일. 갱신: `POST /api/auth/refresh` |
| 민감 액션 인증 | 비밀번호 재확인으로 발급되는 재확인 토큰(10분)을 `X-Reauth-Token` 헤더로 전달 |
| 멱등성 | 부수효과 POST(투자·출금·포인트 전환·입금 알림)는 `Idempotency-Key` 헤더 필수. 누락 시 400 |
| 금액 | 원 단위 정수. 수익률은 `%` 기준 소수점 2자리 문자열(`"9.80"`) |
| 시간 | `ISO 8601` UTC. 표시는 클라이언트 KST 변환 |
| 페이지네이션 | `?page=` `?page_size=` (기본 20, 최대 100) / 커서형은 `?cursor=` |
| 에러 형식 | `{ "code": "ERROR_CODE", "message": "...", "details": {...} }` |

### 1.2 에러 코드

| HTTP | code | 의미 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 필드 검증 실패. `details`에 필드별 사유 |
| 400 | `IDEMPOTENCY_KEY_REQUIRED` | 멱등 키 누락 |
| 401 | `UNAUTHORIZED` | 미로그인/토큰 만료 |
| 401 | `REAUTH_REQUIRED` | 재확인 토큰 필요/만료 |
| 403 | `SUITABILITY_REQUIRED` | 적합성 테스트 미통과·만료 |
| 403 | `GRADE_LIMIT_EXCEEDED` | 등급 투자 한도 초과. `details.remaining_limit` 포함 |
| 403 | `BORROWER_LIMIT_EXCEEDED` | 동일차주 한도 초과 |
| 404 | `NOT_FOUND` | — |
| 409 | `RECRUITMENT_CLOSED` | 모집 중 아님/마감 |
| 409 | `INSUFFICIENT_DEPOSIT` | 예치금 부족. `details.available` 포함 |
| 409 | `INSUFFICIENT_REMAINING` | 잔여 모집액 부족. `details.remaining` 포함 |
| 409 | `STATE_CONFLICT` | 상태머신 전이 불가 |
| 422 | `PIN_LOCKED` | 간편비밀번호 5회 실패 잠금 |
| 500 | `INTERNAL` | — |

### 1.3 상태머신

**상품(Product.status)**
`draft → scheduled → recruiting → recruited → executed → repaying → repaid | overdue | loss`

**투자(Investment.status)**
`active → repaid | overdue | loss | cancelled`

**입금(DepositIntent.status)** `pending → credited | held`

**출금(Withdrawal.status)** `requested → processing → completed | failed`

**예약투자(Reservation.status)** `reserved → converted | cancelled | refunded`

---

## 2. 인증 (F-AUTH)

### POST /api/auth/signup — 투자자 가입
```json
// req
{ "email": "a@b.com", "password": "Abcd1234!", "referrer_email": "c@d.com",
  "agreements": [{ "term": "investment", "agreed": true }, ...] }
// res 201
{ "user_id": 42, "email": "a@b.com", "next_step": "identity_verification" }
```
검증: 이메일 중복(409 `EMAIL_TAKEN`), 비밀번호 정책, 필수 약관 동의.

### POST /api/auth/signup/borrower — 대출자 가입
투자자와 동일 + `agreements`에 `credit_inquiry`·`loan_terms` 필수.

### POST /api/auth/login
```json
// req { "email": "...", "password": "..." }
// res 200 — Set-Cookie: access/refresh
{ "user_id": 42, "name": "...", "grade": "general", "pin_registered": true }
```

### POST /api/auth/login/pin — 간편비밀번호 로그인
```json
// req { "pin": "123456" } — 앱은 네이티브 키패드, 웹은 화면 키패드에서 수집
// res 200 | 422 PIN_LOCKED(5회 실패)
```

### POST /api/auth/logout — 쿠키 삭제 + refresh 무효화

### POST /api/auth/refresh — refresh 쿠키 → 새 access

### POST /api/auth/identity/verify — 본인인증(모의)
```json
// req { "carrier": "SKT", "name": "홍길동", "birth": "19900101", "phone": "010..." }
// res 200 { "ci": "mock-ci-...", "verified": true }
// 409 DUPLICATE_CI — 동일 CI로 가입된 계정 존재
```

### POST /api/auth/pin — 간편비밀번호 등록 `req { "pin": "123456" }`

### POST /api/auth/reauth — 비밀번호 재확인
```json
// req { "password": "..." } → res { "reauth_token": "...", "expires_in": 600 }
```

### POST /api/auth/app-code — "앱으로 로그인" 모사
```json
// 앱이 발급: POST /api/auth/app-code → { "code": "482913", "expires_in": 60 }
// 웹이 교환: POST /api/auth/app-code/exchange { "code": "482913" } → 쿠키 세션
```

---

## 3. 상품 (F-INV-01~03)

### GET /api/products — 상품 목록
쿼리: `status` `type`(scf|stock_loan|mortgage|personal_credit) `min_rate` `max_rate` `min_term` `max_term` `min_amount` `max_amount` `sort`(rate_asc|rate_desc|latest) `include_closed`
```json
// res
{ "results": [{
    "id": 512, "product_no": "2026-512", "name": "아파트 담보대출 152호",
    "type": "mortgage", "annual_rate": "9.80", "term_months": 12,
    "target_amount": 300000000, "raised_amount": 210000000,
    "progress_pct": "70.0", "status": "recruiting",
    "tags": ["조기상환가능"], "registered_at": "2026-10-01T00:00:00Z"
  }], "total": 24, "page": 1 }
```

### GET /api/products/{id} — 상세
```json
{ "id": 512, "product_no": "...", "name": "...", "type": "mortgage",
  "annual_rate": "9.80", "term_months": 12, "repay_type": "equal_installment",
  "target_amount": 300000000, "raised_amount": 210000000, "remaining_amount": 90000000,
  "progress_pct": "70.0", "status": "recruiting", "recruit_open_at": "...", "tags": [...],
  "tabs": { "overview": {...}, "detail": {...}, "notice": "..." },
  "my": { "deposit": 1500000, "investable": 3500000,   // 로그인 시만
          "grade_remaining_limit": 40000000, "same_borrower_remaining": 5000000 } }
```

### GET /api/products/{id}/schedule-preview — 예상수익 계산
```
?amount=10000000
// res
{ "gross_rate": "9.80", "net_rate": "8.29", "gross_return": 980000, "net_return": 829120,
  "schedule": [{ "seq": 1, "pay_date": "2026-11-25", "principal": 816667,
                 "repay_principal": 816667, "interest_gross": 81667,
                 "tax": 12577, "platform_fee": 5000, "interest_net": 64090 }, ...] }
```
계산 규칙(F-INV-03): 세금 15.4%, 상환방식별 스케줄. 반올림 잔액은 마지막 회차가 흡수.

---

## 4. 투자 (F-INV-04~07)

### POST /api/investments — 투자 주문
헤더: `Idempotency-Key` 필수
```json
// req { "product_id": 512, "amount": 1000000, "use_points": 5000 }
// res 201
{ "investment_id": 9012, "amount": 1000000, "points_used": 5000,
  "expected_net_return": 82912, "status": "active",
  "schedule": [...] }
```
- 트랜잭션: 상품 잔액 행 `SELECT FOR UPDATE` → 5중 검증(F-INV-04) → 예치금·포인트 분개 → 투자·스케줄 생성
- 동일 `Idempotency-Key` 재전송 → 200 + 기존 주문 동일 응답
- 실패: `GRADE_LIMIT_EXCEEDED` `BORROWER_LIMIT_EXCEEDED` `INSUFFICIENT_DEPOSIT` `INSUFFICIENT_REMAINING` `RECRUITMENT_CLOSED` `SUITABILITY_REQUIRED`

### GET /api/investments — 내 투자 내역
쿼리: `status`(active|repaid|overdue|loss) `type` `page`

### GET /api/investments/{id} — 건별 상세(회차별 상환 현황 포함)

### GET /api/suitability-test — 문항 조회
```json
{ "questions": [{ "seq": 1, "text": "온투업 투자상품은 예금자보호 대상이다.", "answer_options": ["O","X"] }, ...],
  "valid_until": "2027-10-01T00:00:00Z" | null }
```

### POST /api/suitability-test — 제출·채점(서버)
```json
// req { "answers": [{ "seq": 1, "choice": "X" }, ...] }
// res { "passed": true, "expires_at": "2027-10-01T00:00:00Z" }
```

### 장바구니
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/cart` | 목록 + 합계, 마감 상품 표시 |
| POST | `/api/cart` | `{ "product_id": 512 }` → 201 |
| DELETE | `/api/cart/{id}` | 삭제 |

### 예약 투자
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/reservations/eligible` | 재모집 예약 가능한 내 만기 임박 투자 목록 |
| POST | `/api/reservations` | `{ "investment_id": 9012, "amount": 5000000 }` → reserved |
| PATCH | `/api/reservations/{id}` | 금액 조정 |
| DELETE | `/api/reservations/{id}` | 예약 취소 |

---

## 5. 예치금·가상계좌 (F-DEP)

### GET /api/deposit/account — 가상계좌 + 잔액
```json
{ "bank": "모의은행", "account_no": "100-0000-123456", "holder": "홍길동",
  "deposit": 1500000, "held": 0, "withdrawable": 1500000 }
```

### POST /api/deposit/notify-intent — 입금 알리기(입금 의사 등록)
헤더: `Idempotency-Key`
```json
// req { "sender_name": "홍길동", "amount": 1000000 }
// res 202 { "intent_id": "dep-...", "status": "pending" }
// 이후 모의 은행이 POST /api/webhooks/bank/deposit 발송 → credited
```

### POST /api/deposit/withdraw — 출금 요청
헤더: `Idempotency-Key` + `X-Reauth-Token`
```json
// req { "amount": 500000 } 또는 { "all": true }
// res 202 { "withdrawal_id": "wd-...", "fee": 0, "status": "requested" }
```
수수료: 월 20회 면제, 21회~ 건당 500원(응답 `fee`에 반영).

### GET /api/deposit/history — 예치금 내역
쿼리: `from` `to` `kind`(deposit|withdraw|invest|repay|point|fee) `cursor`
탭 데이터: `GET /api/deposit/history?view=withholding|platform_fee`

### PUT /api/deposit/linked-account — 연결계좌 등록/변경(모의 본인명의 검증)

### PUT /api/deposit/auto-charge — 간편충전 ON/OFF `{ "enabled": true }`

---

## 6. 포인트 (F-PNT)

| 메서드 | 경로 | 응답 |
|---|---|---|
| GET | `/api/points` | `{ "balance": 12500, "expiring_this_month": 2000 }` |
| GET | `/api/points/history?from=&to=&kind=earn|spend|expire` | 분개 목록 + CSV export(`Accept: text/csv`) |
| POST | `/api/points/convert` | 포인트→예치금 전환 `{ "amount": 5000 }` (Idempotency-Key) |

---

## 7. 마이페이지 (F-MY)

### GET /api/me/dashboard — 대시보드 집계
```json
{ "profile": { "name": "...", "grade": "general", "identity_verified": true },
  "virtual_account": {...}, "deposit": 1500000, "points": 12500,
  "limits": { "total_remaining": 40000000, "mortgage_remaining": 20000000 },
  "active": { "invested": 5000000, "principal_remaining": 5000000,
              "interest_received_net": 120400, "interest_expected_net": 380000 },
  "past": { "count": 3, "interest_received_net": 512000 } }
```

### GET /api/me/calendar?year=2026&month=10 — 상환달력
```json
{ "days": [{ "date": "2026-10-25", "principal": 816667, "interest_net": 64090, "status": "scheduled" }],
  "monthly": { "principal_done": 0, "principal_scheduled": 816667,
               "interest_done_net": 0, "interest_scheduled_net": 64090 } }
```

### GET /api/me/grade — 등급·한도 현황 / 변경 이력 `GET /api/me/grade/history`

### POST /api/me/grade-request — 등급 변경 신청(서류 첨부 multipart)
헤더: `X-Reauth-Token`. 상태: `submitted → approved | rejected` → 승인 시 등급 반영.

### POST /api/me/limit-assessment — 원스톱 한도심사(모의): 간편인증 확인 + 소득 서류 업로드

---

## 8. 대출 (F-LOAN)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/loans?category=all|personal|business` | 대출 상품 소개 목록 |
| GET | `/api/loans/{id}` | 상세(특장점·절차·안내표·FAQ) |
| POST | `/api/loans/limit-check` | 간편 한도 조회(모의) `{ "type": "mortgage", "complex": "...", "area": 84, "dong": "101", "ho": "702" }` → `{ "limit": 180000000, "rate_range": ["6.4","14.0"] }` |
| POST | `/api/loans/applications` | 신청(2단계, 첨부 최대 6개 multipart) → 심사 큐 등록 |

---

## 9. 콘텐츠 (F-CON)

| 메서드 | 경로 | 쿼리 |
|---|---|---|
| GET | `/api/notices` | `category` `q` `page` — 상세 `/api/notices/{id}`(첨부 URL 포함) |
| GET | `/api/faqs` | `category` `q` `page` / `GET /api/faqs/keywords` 인기 키워드 |
| GET | `/api/events` | `status`(ongoing|winners|ended) / 상세 + 참여 `POST /api/events/{id}/enter` |
| GET | `/api/disclosures?year=2026&month=9` | KPI + 탭 데이터(management|operations|internal) |
| GET | `/api/news?cursor=` | 카드 목록 |
| GET | `/api/terms/{id}` | 약관 6종 |

---

## 10. 웹훅 — 모의 은행 → API (F-DEP-02/03)

API 쪽 수신 엔드포인트. 공통:
- 헤더 `X-Bank-Signature: t={ts},v1={hmac_sha256(secret, ts + "." + body)}` — 시계 편차 ±5분, 서명 불일치 401
- 본문 `event_id` 유니크 — 재수신 시 200만 반환(처리 스킵)
- 실패 시 모의 은행이 지수 백오프 재시도(최대 8회)

### POST /api/webhooks/bank/deposit — 입금 완료 통지
```json
{ "event_id": "evt-01J...", "type": "deposit.completed",
  "account_no": "100-0000-123456", "sender_name": "홍길동",
  "amount": 1000000, "occurred_at": "..." }
```
처리: intent 매칭(계좌+금액+예금주명) → 원장 입금 분개. 예금주명 불일치 → `held` 보류 큐.

### POST /api/webhooks/bank/transfer — 출금 이체 결과
```json
{ "event_id": "evt-...", "type": "transfer.completed" | "transfer.failed",
  "withdrawal_id": "wd-...", "occurred_at": "..." }
```
`completed` → 원장 출금 확정 분개 / `failed` → 홀드 해제 역분개.

### 모의 은행 측 발행 엔드포인트 (mockbank)
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/mockbank/deposits/execute` | pending intent에 대해 입금 완료 실행(→ 웹훅 발송). `delay_ms`, `force_mismatch` 주입으로 보류 케이스 재현 |
| POST | `/mockbank/transfers/execute` | 출금 이체 실행. `force_fail` 주입 가능 |

---

## 11. 알림·디바이스 (F-APP-05)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/devices` | `{ "expo_push_token": "...", "platform": "ios" }` 등록 |
| POST | `/api/notifications/settings` | 신규 상품·마감·상환 알림 카테고리별 ON/OFF |
| GET | `/api/notifications` | 알림 내역 |

발행 트리거: 상품 `recruiting` 전이, `recruited` 전이, `repay.daily` 배치 완료.

---

## 12. 운영자 (F-ADM) — `/api/admin/*` (staff 권한)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET/POST/PATCH | `/api/admin/products` | 상품 CRUD, `PATCH .../status` 상태 전이 |
| POST | `/api/admin/products/{id}/execute` | 모집완료 → 대출 실행(스케줄 확정·투자금 분개) |
| POST | `/api/admin/batch/repay` `?date=` | 상환 배치 수동 트리거(데모 시간 제어) |
| POST | `/api/admin/batch/expire-points` `/reconcile` | 포인트 소멸 / 원장 대사 |
| GET/PATCH | `/api/admin/grade-requests` | 등급 신청 심사 |
| GET/PATCH | `/api/admin/deposit/holds` | 입금 보류 건 수동 매칭 |
| GET/PATCH | `/api/admin/loan-applications` | 대출 신청 심사 → 상품화 전환 |
| CRUD | `/api/admin/notices` `/faqs` `/events` `/disclosures` `/news` | 콘텐츠 관리 |
| POST | `/api/admin/seed/products` | 가상 상품 대량 생성기(개수·상태·금리 범위 파라미터) |

---

## 13. 부록 — Idempotency-Key 동작 규약

1. 클라이언트는 부수효과 요청마다 UUID v4 키 생성, 재시도 시 같은 키 유지
2. 서버는 `(user, key)` 유니크로 요청을 기록. 동일 키 재수신 → 저장된 응답을 그대로 반환(200)
3. 다른 페이로드 + 같은 키 → 409 `IDEMPOTENCY_KEY_MISMATCH`
4. 키 보존 기간: 24시간
