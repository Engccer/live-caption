# 말동무

청각장애인이 회의·수업·상담 자리에서 상대의 말을 눈으로 따라갈 수 있게 하는 실시간 자막 앱.
주소를 열고 시작 버튼을 한 번 누르면 자막이 나온다. 계정·결제·설정·서버가 없다.

웹앱으로 시작한다. 브라우저에 들어 있는 음성 인식(Web Speech API)을 쓰므로 설치할 것이 없고,
그래서 링크 하나로 건네줄 수 있다. iOS 네이티브 앱은 그다음 단계다.

음성은 브라우저의 인식 서비스로 전송되어 처리된다. 기기 안에서만 도는 것이 아니다.

지금 어디까지 왔는지는 [PROGRESS.md](PROGRESS.md)에 있다.

## 실행

의존성도 빌드도 없다. 정적 파일을 서빙하기만 하면 된다.

```bash
npx serve web
```

`python3 -m http.server`로 열어도 된다. ES 모듈이라 `file://`로 직접 열면 동작하지 않는다.
음성 인식을 지원하는 브라우저(크롬, 사파리)로 연다.

## 테스트

```bash
cd web && node --test
```

브라우저 없이 돈다. 인식 객체와 타이머는 주입해 가짜로 바꾼다.

## 문서

| 문서 | 무엇이 있나 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 이 저장소의 규칙과 실측으로 얻은 함정 |
| [PROGRESS.md](PROGRESS.md) | 지금 참인 상태, 확정된 결정, 알려진 한계 |
| [docs/BACKLOG.md](docs/BACKLOG.md) | 미결 결정, 남은 검증 과제, 뒤집힌 결정 |
| [CHANGELOG.md](CHANGELOG.md) | 날짜별 변경 |
| [웹앱 1차 설계](docs/superpowers/specs/2026-09-13-maldongmu-web-v1-design.md) | 화면·상태·인터페이스 계약 |
| [실시간 STT 스파이크](docs/spike-2026-09-03-realtime-stt.md) | 프로바이더 실호출 측정 전문 |
| [docs/research/](docs/research/) | 국내 프로바이더·국제 오픈소스·국내 시장 조사 |
