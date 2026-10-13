# 데일리펀딩 클론 엔지니어링 노트

데일리펀딩 클론의 문제해결 사례와 구현 경험을 정리한 문서입니다. 각 항목은 문제에서 측정 결과까지 시간 순서로 썼고, 관련 코드와 측정 파일 링크를 함께 뒀습니다.

---

## 문제해결

### TTFB 5.7ms, FCP·LCP 40ms — 정적 셸 우선 스트리밍

초기 목록 화면은 서버 응답이 전부 끝날 때까지 첫 페인트를 기다렸습니다. 투자 목록처럼 상단 헤더와 필터는 정적이고 카드만 데이터가 필요한 화면에서, 전체 응답 대기는 불필요한 지연이었습니다.

`cacheComponents`(PPR)로 라우트를 정적 셸과 동적 부분으로 나눴습니다. 셸은 빌드 시점에 프리렌더돼 즉시 나가고, 상품 데이터가 필요한 부분만 스트리밍으로 뒤따르게 했습니다.

측정은 로컬 프로덕션 빌드(`next start`)와 라이브 Django 백엔드에서 5회 웜 리로드 중앙값으로 잡았습니다. `PerformanceNavigationTiming` 기준 TTFB 5.7ms, FCP·LCP 40ms, DOMContentLoaded 53.7ms였습니다. 측정 조건과 표본은 [vitals-baseline.json](https://github.com/dailyfunding-clone/dailyfunding-fe/blob/develop/apps/fo-web/docs/results/vitals-baseline.json)에 그대로 남겼습니다.

### IP당 동시 스트림 3개, 프레임당 109B — 공유 카운터와 경량 프레임

실시간 진행률 SSE는 두 가지 결함이 있었습니다. 하나는 클라이언트가 위조 가능한 `X-Forwarded-For` 헤더를 연결 식별자로 쓰던 것이고, 다른 하나는 연결 수를 프로세스 로컬 변수로 세던 것이었습니다. 워커가 늘면 각자 따로 세기 때문에 IP당 상한이 실질적으로 작동하지 않았습니다.

식별자를 연결 소켓이 보고하는 `REMOTE_ADDR`로 바꿨습니다. 카운터는 Redis에 옮겨 `INCR`/`EXPIRE`와 `DECR`/`DEL`을 각각 하나의 Lua 스크립트로 묶어 원자적으로 만들고, IP당 동시 스트림 상한 3을 모든 워커가 공유하게 했습니다. 프레임은 상품 ID와 변화량만 담아 약 109B로 줄여, 같은 주기로 전체 스냅샷을 보내는 폴링(294B × N회) 대비 전송량을 낮췄습니다.

코드: [views.py](https://github.com/dailyfunding-clone/dailyfunding-be/blob/develop/api/products/views.py)

### 동일 멱등키 재전송 18건 수렴, oversell 0 — 투자 주문 생애주기와 멱등키

투자 주문은 돈이 나가는 뮤테이션입니다. 버튼 연타, 다른 탭의 동일 주문, 타임아웃 뒤 수동 재시도가 겹치면 같은 주문이 두 번 서버에 도달하고, 응답이 끊기면 성공인지 실패인지 모르는 상태가 남습니다. 실패로 표시하면 성공한 주문을 다시 보내게 되고, 성공으로 표시하면 없던 주문이 생긴 것처럼 보입니다.

기존 구조는 mutation 호출의 성공과 실패 이분만 있어 세 번째 상태를 표현할 자리가 없었습니다. 탭 간 조정도 없어 같은 상품을 연 탭 두 개가 각자 주문을 보낼 수 있었고, 요청마다 새 키가 만들어져 서버가 재시도를 식별하지 못했습니다.

시도(attempt)를 `claim → submit → settle` 생애주기로 모델링했습니다. `claimAttempt`가 스토어에 시도를 선점하면 후발 탭은 follower가 되어 진행 상황만 관전하게 했습니다. `Idempotency-Key`는 시도 생성 시 `crypto.randomUUID()`로 1회 부여해 재시도와 복구에서 같은 키를 재전송하게 하고, 결과를 확인하지 못한 시도는 `ambiguous`로 영속화해 성공과 실패 추측을 막았습니다. 428 재인증 요구는 시도를 유지한 채 토큰만 갱신하게 했습니다.

k6 부하 검증에서 동일 키 재전송 18건이 전부 같은 투자 건으로 수렴했고 oversell은 0건이었습니다. Vitest로 재시도 경로의 `Idempotency-Key` 헤더 유지와 시도 생애주기의 상태 전이를 검증하게 했습니다.

코드: [use-invest-order.ts](https://github.com/dailyfunding-clone/dailyfunding-fe/blob/develop/apps/fo-web/src/app/(site)/investment/_components/use-invest-order.ts), [k6 결과](https://github.com/dailyfunding-clone/dailyfunding-workspace/blob/develop/docs/results/k6-invest.txt)

### WebView 재로드에도 메시지 유실 0 — 버전 핸드셰이크와 seq/ack 재전송 브릿지

Expo 앱이 탭별 WebView로 웹을 띄우는 구조에서 `postMessage`는 언제든 끊기는 파이프이고, WebView가 리로드되면 웹 쪽 자바스크립트 컨텍스트가 통째로 재생성됩니다. 비행 중이던 요청과 네이티브가 이미 보낸 응답이 어긋나면 인증 상태가 갈라지고, 네이티브가 push한 화면 이동 메시지는 웹이 다시 뜨기 전에 유실됩니다.

메시지를 문자열로 주고받는 기존 방식에는 재연결을 감지할 세션 개념도, 전달 보장도 없었습니다. 화면 이동 메시지는 경로 문자열을 그대로 네이티브 라우터에 넘겨 로컬 경로가 아닌 임의 스킴까지 통과할 여지가 있었습니다.

공유 패키지 `packages/bridge`에 양방향 프로토콜을 만들었습니다. 모든 메시지를 `v2 + seq` 봉투로 타입화하고 웹이 `hello`(지원 버전 목록)를 보내 네이티브가 `hello.ack` 또는 `hello.reject`로 협상하게 했습니다. 네이티브는 미확인 메시지를 pending에 보관해 웹의 `ack`으로 지우고, 재연결 뒤 `replay(after)`로 커서 이후분만 재전송하게 했습니다. 웹 쪽은 1초 간격 hello 재시도, 큐 200개, `requestSeq` 매칭과 15초 타임아웃으로 요청-응답을 엮고, `updateAuth`가 pending의 낡은 인증 메시지를 최신 상태로 덮게 했습니다. 화면 이동은 `isLocalPath`로 로컬 경로만 허용해 스킴 주입을 차단하고, 탭별 WebView는 LRU 3개 풀과 스크롤 스냅샷으로 상태를 유지하게 했습니다.

핸드셰이크 협상, 버전 거부, 재로드 후 replay 재전송, 세션 교체 감지를 커버하는 테스트 17개(protocol/web/bridge/pool)가 통과했습니다. 재연결 시 유실 없이 커서 이후 메시지만 재전송되는 것을 테스트로 고정했습니다.

코드: [packages/bridge](https://github.com/dailyfunding-clone/dailyfunding-fe/tree/develop/packages/bridge), [fo-native bridge.ts](https://github.com/dailyfunding-clone/dailyfunding-fe/blob/develop/apps/fo-native/src/features/webview/bridge.ts), [webViewPool](https://github.com/dailyfunding-clone/dailyfunding-fe/blob/develop/apps/fo-native/src/features/webview/pool.ts)

---

## 구현 경험 노트

### 입금 크레딧의 재전송 구분

mockbank 페이로드에 `transfer_id`를 추가하고 `DepositIntent`에 조건부 unique 제약을 걸었습니다. 동일 금액과 동일 입금자명의 정상 재입금이 재전송으로 오인돼 크레딧이 누락되던 경로를 차단했고, 신규 이체와 재전송 dedup을 테스트로 고정했습니다. ([ledger/models.py](https://github.com/dailyfunding-clone/dailyfunding-be/blob/develop/api/ledger/models.py), [test_money_security.py](https://github.com/dailyfunding-clone/dailyfunding-be/blob/develop/tests/test_money_security.py))

### 인증의 경계 정리

웹 로그인 성공을 세션 토큰 대신 일회용 인증 코드로 네이티브에 넘겨 브릿지 메시지에 토큰이 잔류하지 않게 했습니다. 로그아웃 이후 늦게 완료되는 비동기는 generation 카운터로 무효화해 유령 세션 부활을 차단했습니다. ([session.ts](https://github.com/dailyfunding-clone/dailyfunding-fe/blob/develop/apps/fo-native/src/features/auth/session.ts), [reauth.ts](https://github.com/dailyfunding-clone/dailyfunding-fe/blob/develop/apps/fo-native/src/features/auth/reauth.ts))

### 목록 페이지네이션

서버 컴포넌트 첫 페이지의 커서를 `useInfiniteQuery`가 이어받게 해 오프셋 방식의 중복과 누락을 차단했습니다. IntersectionObserver 센티넬과 `requestIdleCallback`으로 다음 페이지를 미리 받아 더보기 대기를 없앴습니다.

### 스토어의 구독 경계

localStorage를 `useSyncExternalStore`로 구독해 SSR 스냅샷과 탭 간 상태가 어긋나지 않게 했습니다. 주문 시도 같은 중간 상태는 Zustand와 TanStack Query mutation으로 모델링했습니다.

### 딥링크와 인증 게이트

앱 전용 URL 스킴과 iOS associated domains, Android autoVerify로 링크를 받고 Expo Router의 네이티브 인텐트 경계에서 앱 라우트로 재작성했습니다. 콜드스타트 링크는 PIN 잠금해제 뒤 목적지로 복귀하게 해 딥링크가 인증 게이트를 우회하지 않게 했습니다.

### 앱의 복구 경로

`expo-network`로 연결 상태를 구독해 오프라인 배너를 띄우고 로드에 실패한 WebView는 온라인 복귀 시 자동 reload하게 했습니다. 루트 ErrorBoundary로 네이티브 렌더 크래시도 재시도 경로로 되돌렸습니다.

### 스트리밍 중 레이아웃 안정

Suspense 경계에 실제 레이아웃과 같은 치수의 스켈레톤을 두고 이미지는 `aspect-ratio`로 자리를 예약해 스트리밍 중 레이아웃 시프트를 막았습니다.

### API 계층의 단일 진입

OpenAPI 스키마에서 타입 생성된 ky 클라이언트에 타임아웃과 GET 한정 재시도, 401 refresh 재시도를 명시했습니다. 오류 본문을 status, code, details로 정규화해 화면마다 에러 형태가 갈라지지 않게 했습니다. ([api.ts](https://github.com/dailyfunding-clone/dailyfunding-fe/blob/develop/apps/bo/src/shared/api/api.ts))

### 앱 배포 경로

EAS 채널별 OTA를 `expo-updates`로 열고 RSA 자체서명 인증서로 코드사이닝해 서명되지 않은 번들이 로드되지 않게 했습니다. ([eas.json](https://github.com/dailyfunding-clone/dailyfunding-fe/blob/develop/apps/fo-native/eas.json))
