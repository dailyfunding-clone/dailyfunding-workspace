# 스택 정의서 — 데일리펀딩 클론

- 문서 버전: v2.0 · 작성일: 2026-10-01
- 선정 기준: 데일리펀딩 실서비스가 사용하는 기술 스택과 동일하게 채택(실서비스: React·Next.js·TypeScript·zustand·panda-css·React Native / Python·Django·DRF·RDBMS)

---

## 1. 저장소 구조

```
dailyfunding-workspace/        # 통합 워크스페이스 (문서·스크립트)
├─ dailyfunding-fe/            # 프론트엔드 저장소 (pnpm monorepo)
│  ├─ apps/web/                # Next.js — 투자자/대출자/운영자 웹 (단일 배포 단위)
│  ├─ apps/mobile/             # Expo React Native — 네이티브 셸 + WebView
│  └─ packages/
│     ├─ design-system/        # panda-css 토큰·recipes·patterns
│     ├─ bridge/               # JS↔Native 타입드 postMessage 프로토콜
│     └─ api-client/           # OpenAPI 타입 생성 + fetch 클라이언트
└─ dailyfunding-be/            # 백엔드 저장소 (Python)
   ├─ api/                     # Django + DRF 서비스
   └─ mockbank/                # 모의 은행 (입금·이체 웹훅 발행기)
```

FE/BE는 별도 저장소. 계약 동기화: BE CI가 `schema.json`을 생성해 아티팩트로 배포 → FE CI가 내려받아 타입 생성 후 diff 검증(불일치 시 실패).

---

## 2. Frontend (dailyfunding-fe)

### 2.1 Web — `apps/web`

| 영역 | 선택 | 근거 |
|---|---|---|
| 프레임워크 | Next.js 15 (App Router) | SSR로 공개 페이지 서빙, WebView에서도 HTML 우선 표시 |
| 언어 | TypeScript strict | 전 영역 타입 안전 |
| UI | React 19 | 실서비스와 동일 |
| 클라이언트 상태 | zustand | 실서비스와 동일 |
| 서버 상태 | TanStack Query | 요청 캐시·낙관적 업데이트(투자 주문·장바구니) |
| 스타일 | panda-css | 실서비스와 동일. 디자인 시스템과 동일 엔진 |
| 폼/검증 | react-hook-form + zod | 신청 폼·주문 폼 검증 |
| API 클라이언트 | openapi-typescript 생성 타입 + fetch 래퍼 | 스키마-타입 일치 보장 |
| 인증 | httpOnly 쿠키 세션(JWT) + 재확인 토큰 | 2차 인증 게이트 구현 |

### 2.2 Mobile — `apps/mobile`

| 영역 | 선택 | 근거 |
|---|---|---|
| 셸 | Expo SDK + React Native | 실서비스의 크로스플랫폼 앱 방식과 동일 |
| 네비게이션 | Expo Router | 탭·스택 전환, 딥링크 |
| WebView | react-native-webview | 콘텐츠 화면은 웹과 동일 페이지를 표시. 탭별 인스턴스 상주 |
| 생체인증 | expo-local-authentication | 금융앱 잠금·로그인 |
| 보안 저장소 | expo-secure-store | refresh 토큰 보관 |
| 푸시 | expo-notifications | 상품 오픈·마감·상환 알림 |
| 브릿지 | `packages/bridge` 자작 타입드 postMessage 프로토콜 | WebView 경계 계약. 타입 공유로 오류 방지 |

### 2.3 Design System — `packages/design-system`

- panda-css: tokens(색상·간격·타이포)·recipes·patterns·조건부 스타일
- 산출물: ① CSS/런타임 (web·WebView 공용) ② `tokens.json` → app의 네이티브 chrome(탭바·스플래시·인증 화면) 스타일 소스
- 웹과 앱 네이티브 UI가 같은 토큰을 참조 → 디자인 시스템 단일 소스

### 2.4 API Client — `packages/api-client`

- `openapi-typescript`가 BE `schema.json`에서 타입 생성
- 얇은 fetch 래퍼: 공통 에러 형식, `Idempotency-Key` 자동 부여, 재확인 토큰 헤더

---

## 3. Backend (dailyfunding-be)

| 영역 | 선택 | 근거 |
|---|---|---|
| 언어/프레임워크 | Python 3.12 + Django 5 | 실서비스 백엔드와 동일 |
| API | Django REST Framework | 실서비스와 동일 |
| API 문서 | drf-spectacular → OpenAPI 3 스키마 | FE 타입 생성 소스 |
| 인증 | djangorestframework-simplejwt (access + refresh, httpOnly 쿠키) | 웹·앱 공용. 재확인 토큰 별도 발급 |
| DB | PostgreSQL 16 | `SELECT FOR UPDATE`·CHECK 제약 활용 |
| 마이그레이션 | Django migrations | — |
| 배치/비동기 | Celery + Redis | 상환 배치·포인트 소멸·대사 배치·웹훅 재시도 |
| 금액 | DecimalField / 원단위 정수 | 금융 정합성. 부동소수점 금지 |
| 테스트 | pytest + pytest-django, factory_boy | — |
| 부하/검증 | k6 (투자 경합·멱등 시나리오) | 초과 모집 0건 등 측정 수치 확보 |

### 3.1 모의 은행 (mockbank)

- 같은 BE 저장소 내 별도 Django 앱 또는 경량 프로세스
- 역할: 가상계좌 입금 완료 웹훅 발행, 출금 이체 상태머신, 연결계좌 즉시 이체
- 계약: `POST /api/webhooks/bank/deposit` HMAC-SHA256 서명 + `event_id`(멱등) + 재시도(지수 백오프)
- API는 웹훅을 실제 외부 이벤트처럼 처리 → 연동 경계가 실제로 존재

### 3.2 도메인 모델 핵심

```
User ─┬─ VirtualAccount ──┬─ LedgerEntry (예치금 원장)
      ├─ InvestorGrade ── LimitRule
      ├─ PointEntry (포인트 원장)
      ├─ Investment ── RepaymentSchedule[] ── RepaymentEvent
      └─ SuitabilityTest (1년 유효)

Product ── 모집(Tranche) ── 상태머신(모집예정→모집중→모집완료→실행→상환중→완료/연체/손실)
LoanApplication ── 심사 → Product 전환
WebhookEvent (수신 웹훅 로그, 멱등 키)
```

정합성 원칙: 잔액은 원장 분개의 합으로만 산출, 투자 주문은 단일 트랜잭션 + 행 잠금, 배치는 멱등(동일 지급 회차 재실행 시 중복 지급 없음).

---

## 4. 인프라·운영

| 영역 | 선택 |
|---|---|
| 로컬 개발 | Docker Compose (api + postgres + redis + mockbank + web) |
| CI | GitHub Actions — 린트/테스트/타입검사/schema diff 검증 |
| 배포 | AWS EC2(api+mockbank) · RDS Postgres · S3+CloudFront(web 정적) 또는 Vercel(web) |
| 모니터링 | Sentry(웹/API), 구조화 로그(JSON) |
| 환경변수 | `.env` 로컬 / 시크릿은 CI 시크릿 스토어 |

---

## 5. 실서비스 스택 대응 표

| 실서비스 사용 기술 | 본 프로젝트 |
|---|---|
| React · SPA | web 전체 + app WebView 콘텐츠 |
| Next.js (SSR) | 상품 목록·상세·콘텐츠 SSR — WebView 첫 화면에도 활용 |
| TypeScript | web·app·packages 전체 strict |
| panda-css / CSS-in-JS | panda-css 디자인 시스템 |
| React Native | 네이티브 셸 앱 |
| zustand | 클라이언트 상태 |
| Python · Django · DRF | api 전체 |
| RDBMS | PostgreSQL |
| JIRA | GitHub Issues/Projects로 대체 |

---

## 6. 채택하지 않은 기술

| 기술 | 이유 |
|---|---|
| Module Federation | 독립 배포 단위가 웹 1개뿐이라 런타임 조립 대상이 없음. WebView 로딩 지연만 추가됨 |
| 마이크로서비스 | 단일 서비스 도메인. 원장·투자 정합성을 모놀리스 트랜잭션 안에서 처리하는 것이 설계 의도 |
| 실제 PG/은행 API | 사업자·제휴 필요. 모의 은행 + 웹훅으로 경계 설계를 대체 |
