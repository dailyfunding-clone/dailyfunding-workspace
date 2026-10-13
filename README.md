# dailyfunding-workspace

- `dailyfunding-fe/` — `apps/fo-web` Next.js 16 웹 + `apps/fo-native` Expo 모바일 + `apps/bo` 어드민 (pnpm + turbo)
- `dailyfunding-be/` — Django/DRF API + mockbank + Celery
- `docs/` — PRD, 기능/API 명세, 스택 정의, [개발 노트](docs/dev-notes/engineering-notes.md)

## 스크린샷

### fo-web

| 홈 | 투자 상품 | 상품 상세 |
|---|---|---|
| ![fo-web 홈](https://github.com/dailyfunding-clone/dailyfunding-fe/raw/develop/docs/screenshots/fo-web/home.png) | ![fo-web 투자](https://github.com/dailyfunding-clone/dailyfunding-fe/raw/develop/docs/screenshots/fo-web/investment.png) | ![fo-web 상품 상세](https://github.com/dailyfunding-clone/dailyfunding-fe/raw/develop/docs/screenshots/fo-web/investment-detail.png) |

### fo-native

| 앱 랜딩 | 홈 탭 | 투자 탭 |
|---|---|---|
| ![네이티브 랜딩](https://github.com/dailyfunding-clone/dailyfunding-fe/raw/develop/docs/screenshots/fo-native/auth-landing.png) | ![네이티브 홈](https://github.com/dailyfunding-clone/dailyfunding-fe/raw/develop/docs/screenshots/fo-native/tab-home.png) | ![네이티브 투자](https://github.com/dailyfunding-clone/dailyfunding-fe/raw/develop/docs/screenshots/fo-native/tab-investment.png) |

### bo

| 상품 관리 | 배치 |
|---|---|
| ![bo 상품](https://github.com/dailyfunding-clone/dailyfunding-fe/raw/develop/docs/screenshots/bo/products.png) | ![bo 배치](https://github.com/dailyfunding-clone/dailyfunding-fe/raw/develop/docs/screenshots/bo/batch.png) |

전체 스크린샷은 `dailyfunding-fe` 레포 `docs/screenshots/`에 있다.

## 모바일 푸시

- Expo 프로젝트 `@cyjoon/dailyfunding-mobile` (projectId `c81d692d-…`, `apps/fo-native/app.json` `extra.eas`)
- 토큰 발급/등록 코드: `apps/fo-native/src/lib/push.ts` → `POST /api/devices` (실기기 필요 — 시뮬레이터는 `Device.isDevice=false`로 스킵)
- Android: Firebase 프로젝트 `dailyfunding-48763` + FCM V1 service account Expo 등록 완료
  - `google-services.json` 적용 (네이티브 재생성 시 `bunx expo prebuild -p android` 후 빌드)
- iOS: 보류 — APNs key는 유료 Apple Developer Program($99/yr) 필수, 우회 없음.
  iOS에서 토큰 발급 코드는 동작하나 실발송 불가. 결제 후 `eas credentials`로 `.p8` 업로드하면 완성
