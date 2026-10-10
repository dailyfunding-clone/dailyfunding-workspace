# dailyfunding-workspace

- `dailyfunding-fe/` — `apps/fo-web` Next.js 16 웹 + `apps/fo-native` Expo 모바일 + `apps/bo` 어드민 (pnpm + turbo)
- `dailyfunding-be/` — Django/DRF API + mockbank + Celery
- `docs/` — PRD, 기능/API 명세, 스택 정의

## 검증 스크립트

| 스크립트 | 내용 |
|---|---|
| `scripts/e2e-lifecycle.py` | 가입→인증→적합성→reauth→계좌→충전→투자→실행→상환→출금 22단계 |
| `scripts/race-invest.py` | 투자 경합·멱등 — oversell 0, Idempotency-Key 재시도 일치 |
| `scripts/load-invest.k6.js` | 동일 시나리오 k6 버전 (`k6 run -e PRODUCT_ID=<id>`) |

전제: `dailyfunding-be` 컨테이너 기동 (`docker compose up`), 시드 적용.

## 모바일 푸시

- Expo 프로젝트 `@cyjoon/dailyfunding-mobile` (projectId `c81d692d-…`, `apps/fo-native/app.json` `extra.eas`)
- 토큰 발급/등록 코드: `apps/fo-native/src/lib/push.ts` → `POST /api/devices` (실기기 필요 — 시뮬레이터는 `Device.isDevice=false`로 스킵)
- Android: Firebase 프로젝트 `dailyfunding-48763` + FCM V1 service account Expo 등록 완료
  - `google-services.json` 적용 (네이티브 재생성 시 `bunx expo prebuild -p android` 후 빌드)
- iOS: 보류 — APNs key는 유료 Apple Developer Program($99/yr) 필수, 우회 없음.
  iOS에서 토큰 발급 코드는 동작하나 실발송 불가. 결제 후 `eas credentials`로 `.p8` 업로드하면 완성
