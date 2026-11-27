# Phase 5 — 도로변 수신 구조 C 설계 (연속 스캔 + 광고별 콜백)

상태: **설계만. 구현·업로드 전** (사용자 결정: 실물 ON/OFF 5회 기준선을 먼저 확보한 뒤 구현, 2026-11-27)

## 1. 결정과 범위

| 항목 | 결정 |
|---|---|
| 수신 방식 | C: `start(0)` 연속 스캔 + 광고마다 콜백 → 고정 크기 큐 → `loop()`에서 판단·출력 |
| 유지 | BLE 광고 6바이트 형식, XIAO 송신 펌웨어, `WarningController`(WAITING/WARNING 규칙), `keyring_packet` |
| 되돌리기 | 기준선 커밋에 태그 `roadside-scan1s-baseline`. 회귀 시 `git checkout roadside-scan1s-baseline -- src/roadside/main.cpp` 후 재빌드·업로드 |
| 범위 밖 | RSSI 거리 판정·임계값, 대시보드, LED판, 고장 시 LED 정책(안전 요구사항 미정) |

## 2. 근거 — 설치된 Arduino-ESP32 2.0.17 `libraries/BLE/src`

| 사실 | 위치 |
|---|---|
| 스캔 시간 단위는 초. `start(0)` = 멈출 때까지 계속 | `BLEScan::start` → `esp_ble_gap_start_scanning(duration)` |
| 콜백 등록 + `wantDuplicates=true`이면 광고마다 `onResult()` 호출, 결과를 저장하지 않고 `delete` | `BLEScan.cpp` `ESP_GAP_SEARCH_INQ_RES_EVT` |
| `wantDuplicates=false`이면 콜백이 있어도 결과를 map에 저장 → 연속 스캔에서 계속 쌓임(메모리) | 같은 곳 |
| 컨트롤러 중복 필터 꺼짐 | `scan_duplicate = BLE_SCAN_DUPLICATE_DISABLE` |
| `stop()`은 완료 콜백을 부르지 않고 세마포어만 반환 → `stop()` 후 `start()` 가능 | `BLEScan::stop` |
| 완료 콜백은 `ESP_GAP_SEARCH_INQ_CMPL_EVT`(시간 만료·컨트롤러가 종료)에서만 | 같은 파일 |
| 광고마다 `new BLEAdvertisedDevice` + 파싱 + `delete` (BT 태스크) | 같은 곳 — 주변 광고가 많으면 BT 태스크 부하·힙 할당 반복 |
| 스캔 시작 후 비동기 실패(scan start complete status)는 `BLEScan`이 처리 안 함 | 기존 README 한계 2 |

**광고 100ms ≠ 초당 10개 수신.** 스캔 창/주기(99/100ms), 3개 광고 채널 순환, 충돌, BT 태스크 처리 속도 때문에 실제 수신 수는 실측으로만 판단한다.

## 3. 구조

```
[BT 태스크]  onResult(device)
   ├─ 모든 광고: allAdvCount++ (atomic)            ← 수신기 동작 진단용
   └─ Manufacturer Data가 키링 형식(parsePayload)일 때만
        이벤트 {millis(), payload[6], rssi} 를 큐에 push (실패 시 dropCount++)
        ※ Serial·GPIO·WarningController 호출 금지

[loop 태스크] 약 10ms마다
   1) 큐를 모두 꺼내 controller.onAdvertisement(payload, 6, 이벤트 시각) → [LED]/[RX]/[STATE] 출력
   2) controller.update(millis())  → 신호 소실 판정 (기존 규칙 그대로)
   3) 스캔 상태 점검·복구 (4절)
   4) 약 10초마다 [ALIVE] (+ 진단 값)
```

큐: lib/core의 **단일 생산자·단일 소비자 고정 크기 링 버퍼**(용량 32 예정, 넘치면 새 이벤트를 버리고 드롭 수 증가).
- FreeRTOS 큐 대신 쓰는 이유: 맥북에서 넘침·순환·동시 접근(스레드 2개 + ThreadSanitizer)까지 단위 테스트할 수 있다.
- 대가: 직접 만든 동시성 코드 → 생산자 1·소비자 1 전제를 코드 주석과 테스트로 고정한다.
- 넘칠 때 새 이벤트를 버려도 되는 이유: 경고 판단에는 "최근에 받았다"만 필요하고, 큐 안의 이벤트가 이미 그 사실을 담고 있다.

이벤트 시각은 콜백에서 찍은 `millis()` → 스캔 종료 시각으로 기록하던 오차(최대 약 1.1초)가 사라진다. 큐는 FIFO, 생산자 하나라 시각이 단조 증가하고, `loop()`가 큐를 먼저 비운 다음 `update(millis())`를 부르므로 `lastSeen ≤ now`가 유지된다.

## 4. 이상 구분과 복구 정책

| 상황 | 판단 근거 | 로그 | 복구 | 경고 상태 |
|---|---|---|---|---|
| 키링 신호 소실 | 스캔 정상(아래 이상 없음) + 키링 이벤트가 timeout(3000ms) 동안 없음 | `[STATE] WARNING -> WAITING` | 없음(정상 동작) | WAITING (기존) |
| 스캔 시작 실패 | `start(0)`이 false | `[SCAN ERROR]` (기존 형식) | 1초 뒤 재시도 | 변경 없음 → 실패가 이어지면 timeout 뒤 WAITING (기존과 같음) |
| 스캔이 끝나 버림 | 완료 콜백 호출(연속 스캔에선 원래 오지 않음) | `[SCAN ENDED]` | 즉시 `start(0)` 재시작 | 변경 없음 |
| 수신기 이상 **의심** | 모든 기기의 광고가 `kStallMs`(예정 10000ms) 동안 0개 | `[SCAN STALL?]` (구간당 1회) | `stop()` → `start(0)` 재시작, 재시작 횟수 기록 | 변경 없음 |
| 큐 넘침 | 드롭 수 증가 | `[ALIVE] ... q_drop=` | 없음(진단) | 변경 없음 |

- **주변 광고 0개 ≠ 고장.** BLE 기기가 없는 장소에서도 0개가 된다. 그래서 이름에 `?`를 붙이고 판정이 아니라 "재시작해 볼 근거"로만 쓴다. 재시작은 정상 상태에서도 해가 없다.
- 자동 재부팅(watchdog)과 고장 시 LED 표시는 넣지 않는다(상태가 초기화되고, 안전 정책이 정해지지 않음). `[ALIVE]`가 끊기면 loop 정지다.

`[ALIVE]` 추가 값(기존 앞부분 형식 유지, 뒤에 덧붙임): `adv=`(모든 광고 누적), `kr=`(키링 이벤트 누적), `q_drop=`, `q_max=`(큐 최대 사용량), `restarts=`, `heap=`/`heap_min=`(`ESP.getFreeHeap/getMinFreeHeap`).

## 5. 시험

### 하드웨어 없이 (맥북, `scripts/run_tests.sh`)

| 시험 | 확인 |
|---|---|
| 기존 88개 검사 | 그대로 통과 (회귀) |
| 링 버퍼: 빈 큐 pop 실패, 순서 유지, 용량까지 push, 넘침 시 드롭 수·기존 내용 보존, 순환(wrap) 반복 | 단위 테스트 |
| 링 버퍼 동시 접근: 생산자·소비자 스레드로 10만 개, 누락 = 드롭 수, 순서 유지 | 스레드 테스트 + ThreadSanitizer 빌드 |
| 스캔 이상 판단: 광고 계속 → 정상, `kStallMs` 무광고 → 1회만 보고, 광고 재개 → 해제, 경계값, millis 순환 | 단위 테스트 |
| 상태 전환(광고별 이벤트): 100ms 간격 키링 이벤트 → WARNING 1회만, 마지막 이벤트 + 3000ms에 WAITING, 중복 이벤트로 추가 전환 없음 | 단위 테스트 |

### 실물 (변경 후, 기준선과 같은 절차)

- `scripts/onoff_latency.py`로 ON/OFF 5회 → 기준선과 비교: 해제 지연(USB 분리 → WAITING, 마지막 RX → WAITING) 중앙값·최대, 감지 지연(USB 연결 → 첫 RX), 초당 수신 수, 최대 수신 간격, 오수신, 이상 이벤트.
- **XIAO 쪽 지연과 ESP32 쪽 지연 분리**: 연결 → 첫 RX = XIAO 부팅 + XIAO 시리얼 대기(코드상 최대 2000ms, 맥북에서 아무도 포트를 열지 않으면 2000ms 전부) + ESP32 처리 지연. 변경 전후 차이가 ESP32 처리 지연 변화이고, XIAO 대기는 XIAO 쪽 시각 측정(별도 결정)으로 확인한다.
- 장시간: XIAO ON 상태로 30분 이상 → `[ALIVE]`의 heap·heap_min 추세, q_drop, restarts.

### 성공 기준 (사용자 지정)

유효 광고 → WARNING / 소실 → WAITING / 중복 광고로 불필요한 전환 없음 / 수신 빈도·지연의 실제 개선을 실측으로 확인 / 큐 넘침·스캔 이상을 로그로 진단 가능 / 비정상 메모리 증가·정지 없음.
