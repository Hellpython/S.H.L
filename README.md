# 어린이 키링 BLE 경고 — 1차 프로토타입

어린이 키링(ESP32)이 BLE 광고를 보내면, 도로변 장치(ESP32)가 이를 받아 LED를 켜는 최소 시스템.

```
[키링 ESP32] --BLE 광고(6바이트)--> [도로변 ESP32] --> 경고 판단 --> LED ON/OFF
```

> **연구실 시험하러 왔다면** → [연구실 시험 안내](docs/lab-guide.md) → [시험 체크리스트](docs/lab-test-checklist.md)
> 시작 명령: `./scripts/lab.sh help`

## 현재 상태 (2026-11-12)

| 구분 | 내용 |
|---|---|
| 구현 완료 | 광고 데이터 형식, 경고 판단 로직, 키링 송신·도로변 수신 펌웨어, GPIO LED 출력 |
| 테스트 통과 (맥북, 가짜 BLE 이벤트) | 14개 케이스 / 88개 검사 통과 |
| 빌드 확인 | `esp32dev` 기준 `keyring`, `roadside` 펌웨어 빌드 성공 |
| **실물 검증 필요** | 실제 BLE 송수신, 감지·소실, LED 동작, 거리별 시험 — **아직 한 번도 하지 않음** |

## 구조

```
platformio.ini          빌드 환경 2개: keyring / roadside (board = esp32dev, 가정)
include/app_config.h    모든 실험용 설정값 + 잘못된 조합을 막는 static_assert
lib/core/               하드웨어와 무관한 순수 C++ (맥북에서 테스트)
  keyring_packet.*        광고 데이터 만들기/해석하기
  warning_controller.*    WAITING/WARNING 상태 판단 + 바뀔 때만 출력 명령
src/keyring/main.cpp    키링: BLE 광고 송출
src/roadside/main.cpp   도로변: BLE 스캔 → 판단 → LED
test/test_core.cpp      가짜 BLE 이벤트·가짜 LED로 판단 로직 검증
scripts/run_tests.sh    판단 로직 단위 테스트 실행
scripts/lab.sh          연구실 명령 모음 (점검·포트·빌드·업로드·모니터·테스트)
scripts/test_lab.sh     lab.sh 셀프테스트 (모의 pio, 실제 USB 안 씀)
docs/lab-guide.md       연구실 시험 안내 (연결·업로드·로그 읽는 법)
docs/lab-test-checklist.md  연구실 시험 순서·기록표
docs/                   그 밖에 검토 기록, 진행 현황
```

## 실행

```sh
./scripts/lab.sh doctor                    # 도구 점검
./scripts/lab.sh test                      # 맥북 단위 테스트 (의존성 없음)
./scripts/lab.sh build                     # 펌웨어 2종 빌드
./scripts/lab.sh ports                     # ESP32 USB 포트 찾기
./scripts/lab.sh upload keyring  <포트>     # 키링(송신) 업로드 — 대상 표시 후 y 확인
./scripts/lab.sh upload roadside <포트>     # 도로변(수신) 업로드
./scripts/lab.sh monitor <포트>             # 시리얼 로그 (115200, Ctrl+C 종료)
```

`lab.sh`는 VS Code PlatformIO 확장의 PlatformIO(`~/.platformio/penv/bin/pio`)를 우선 쓴다. 소스·설정 파일은 수정하지 않지만, build/upload/test는 `.pio/`, `.build/`와 PlatformIO 패키지·캐시(`~/.platformio`)를 갱신할 수 있다. `PIO` 환경변수로 다른 pio를 지정하면 그 실행 파일을 그대로 쓰므로 `doctor`로 경로·버전을 확인한다.

## 설계 이유

- **판단 로직을 BLE와 분리**: ESP32 없이도 맥북에서 시간 조건을 정확한 값으로 테스트할 수 있다. 펌웨어는 "스캔 결과를 넘겨주고, LED를 켜고 끄는" 얇은 연결부만 맡는다.
- **스캔 1회씩 끝까지 기다린 뒤 처리**: `scan->start(1초, 완료콜백)`으로 스캔 시작 오류를 받는다. 완료 콜백(BLE 태스크)은 `std::atomic<bool>` 플래그만 세우고, 결과 처리·판단·LED는 모두 `loop()`에서 한다 → BLE 태스크와 공유하는 상태는 이 플래그 하나뿐. 대가: 수신 시각을 스캔 종료 시각으로 기록한다(아래 알려진 한계 1).
- **Manufacturer Data 6바이트**: Company ID + 'CS' 표식 + 버전 + 키링 번호. 길이·각 바이트를 모두 검사해 다른 BLE 장치를 걸러낸다. 이름·연락처는 넣지 않지만, 고정 번호·주소에 의한 추적 위험은 남아 있다(알려진 한계 4).
- **출력은 상태가 바뀔 때만**: 같은 키링 신호가 수십 번 와도 LED 명령은 1번.
- **추가 라이브러리 없음**: Arduino-ESP32 core 2.0.17에 들어 있는 BLE 라이브러리만 사용.
- **Arduino-ESP32 버전 고정**: core 3.x는 BLE API가 달라 그대로는 빌드되지 않을 수 있다(미확인).

## 알려진 한계

1. **수신 시각 오차**: 스캔 중 받은 신호를 스캔이 끝난 시각으로 기록한다. 설계상 오차는 스캔 시간(1초) 수준이지만, 콜백·`loop()` 재개 지연, 광고 누락까지 포함한 실제 감지 지연·오차 상한은 **미확인**(실물 측정 필요). 경고 종료는 늦어지는 쪽으로 오차가 생긴다.
2. **스캔 실패는 일부만 구분됨**: `BLEScan::start()`가 즉시 반환하는 스캔 *시작* 오류만 `[SCAN ERROR]`로 기록한다. 시작 명령이 받아들여진 뒤 비동기로 오는 실패(classic ESP32의 scan param/start complete status)는 `BLEScan`이 처리하지 않아 **현재 구현은 감지하지 않는다**. `BLEDevice::setCustomGapHandler()`로 GAP 이벤트를 직접 받으면 감지할 수 있지만 구현하지 않았다. `BLEDevice::init()`은 성공 여부를 반환하지 않고(일부 실패는 라이브러리 `[E]` 로그로만 보임), `getInitialized()`도 성공 확인 수단이 아니다. 스캔 완료 이벤트가 오지 않으면 `loop()`가 대기 상태로 멈출 가능성이 있다(미확인). 스캔이 실패해도 경고 상태는 "신호 없음"과 같게 처리되어, 실패가 계속되면 타임아웃 뒤 LED가 꺼진다(수신기 고장과 어린이 없음이 LED로는 구분되지 않음). 실패 시 LED 정책은 미정.
3. **위조 가능**: 같은 6바이트를 광고하면 누구나 키링으로 인식된다. Company ID `0xFFFF`는 테스트용이다.
4. **추적 가능성(개인정보)**: 고정된 키링 번호와 고정 BLE 주소(public MAC)가 반복 송출된다. 제3자가 특정 키링을 따라갈 수 있다. → **연구실 시험 전용. 실제 어린이에게 지급 금지.**
5. RSSI는 로그로만 남긴다. 거리 값이 아니다.
6. **스캔 정지와 키링 부재를 완전히 구분하지 못함**: 수신기는 약 10초마다(스캔 회차 경계에 맞춰 찍히므로 더 늦을 수 있음) `[ALIVE]` 로그를 찍어 `loop()`가 최근에 반복됐음을 보여 준다. 20초 넘게 끊기면 정지를 의심할 수 있지만, `[ALIVE]`가 나온다고 스캔 성공이나 수신 가능 상태가 보증되지는 않는다(한계 2의 실패는 드러나지 않음).
7. **장치 오류 시 안전한 경고 정책 미정**: 스캔 실패·수신기 이상 때 LED를 어떻게 할지(켜 둘지, 고장 표시를 할지) 정하지 않았다. 현재는 "신호 없음"과 같게 처리된다.
8. 이 프로토타입은 안전장치 수준의 신뢰성이나 개인정보 보호를 확보하지 않았다.
9. Flash 사용률 약 85%(원인별 크기는 분석하지 않음). Wi-Fi 등을 추가하면 파티션 조정이 필요할 수 있다.
