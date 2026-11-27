# XIAO nRF52840 키링 전환 기록

키링(송신)을 ESP32에서 Seeed Studio XIAO nRF52840으로 바꾸는 작업의 진행 기록.
기존 `keyring`(ESP32 키링), `roadside`(ESP32 도로변) 환경은 그대로 두고 `keyring_xiao` 환경을 추가했다.

표기: **확인** = 이 기록에 적힌 명령으로 실제 실행해 본 결과 / **미검증** = 아직 실행하지 않음

## 1. 현재 단계 (2026-11-27)

| 단계 | 상태 |
|---|---|
| Phase 0 기준선 (기존 빌드·테스트) | 확인 |
| Phase 1 `keyring_xiao` 환경 + 최소 시리얼 펌웨어 빌드 | 확인 (빌드만) |
| 보드 모델 확인 (일반형 / Sense) | **미확인 — 업로드 보류 중** |
| Phase 2 USB 업로드, 시리얼 로그, 재연결 후 실행 | **미검증** |
| Phase 3 BLE 광고 구현·실제 송신 | **미구현 / 미검증** |
| Phase 4 ESP32 실제 수신, WAITING → WARNING → WAITING | **미검증** |
| Phase 5 반복·실패·경계 시험 (실물) | **미검증** |
| 배터리 구동, LED판 점등, 거리 기반 감지 | **범위 밖. 구현·검증 안 함** |

## 2. 개발 환경 (확인)

| 항목 | 값 |
|---|---|
| 맥북 | arm64, macOS 27.0.1, **Rosetta 2 없음** (`arch -x86_64 /usr/bin/true` → Bad CPU type) |
| PlatformIO | `~/.platformio/penv/bin/pio` 6.2.0 (`lab.sh`가 사용) |
| 플랫폼 | `platform-seeedboards` 1.1.1, 커밋 `a6fd41debbbcda13b5340fff50c9092ed3289194`로 고정 |
| 보드 | `seeed-xiao-afruitnrf52-nrf52840` (일반형, Adafruit 계열 core) |
| 프레임워크 | `framework-arduinoadafruitnrf52` 1.10101.0 = "Seeed nRF52 Boards" 1.1.1 |
| 툴체인 | `toolchain-gccarmnoneeabi` 1.100301.220327 = **GCC 10.3.1, arm64 네이티브** |
| 업로드 도구 | `tool-adafruit-nrfutil` 1.503.0, 프로토콜 `nrfutil`, 1200bps 터치로 부트로더 진입 |
| SoftDevice | s140 7.3.0 (보드 정의 기준) |

프레임워크는 Seeed 서버의 버전 표기 없는 tarball(`files.seeedstudio.com/arduino/platformio/framework-arduinoadafruitnrf52.tar.bz2`)에서 받는다 → 플랫폼 커밋을 고정해도 프레임워크 내용이 바뀔 수 있다(재현성 한계).

## 3. 빌드 오류와 해결

### 3-1. `Bad CPU type in executable`

```
sh: /Users/heechan/.platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-g++: Bad CPU type in executable
*** [.pio/build/keyring_xiao/src/keyring_xiao/main.cpp.o] Error 126
```

- 원인: 플랫폼이 툴체인을 `>=1.60301.0,<1.80000.0`으로 제한 → 1.70201.0(GCC 7.2.1) 설치. 이 바이너리는 `Mach-O 64-bit executable x86_64`이고 Rosetta가 없어 실행 불가.
- 레지스트리 조회(`api.registry.platformio.org`) 결과: 1.90301 이하 버전은 `darwin_arm64` 태그가 있어도 실제 파일은 `darwin_x86_64` 하나. 네이티브 arm64 파일은 1.100301.220327(GCC 10.3.1)부터 있다.

### 3-2. GCC 10.3.1을 고른 이유

| 선택지 | 장점 | 단점 |
|---|---|---|
| **GCC 10.3.1 (선택)** | 프로젝트 설정(`platform_packages`)만 바꿈, 시스템 변경 없음. 네이티브 arm64 중 가장 낮은 버전 | Seeed 지정 범위(<1.8) 밖. Adafruit 원본 core의 GCC 9.2와도 다름 |
| Rosetta 2 설치 | Seeed 지정 GCC 7.2.1 그대로 | 시스템 전역 변경. Apple이 Rosetta를 축소하는 중이라 장기 유지 불확실(미검증) |
| GCC 12/14 | 최신 | 지정 버전과 차이가 더 큼 |

사용자 결정(2026-11-27): GCC 10.3.1.
영향: 프로젝트 소스 컴파일 경고 0건(확인). 컴파일러 차이로 인한 **런타임 차이 여부는 실물 실행 전까지 미검증**.

### 3-3. `undefined reference to Serial`

```
main.cpp:(.text._write+0x8): undefined reference to `Adafruit_USBD_CDC::operator bool()'
main.cpp:(.text._write+0x20): undefined reference to `Serial'
```

- Seeed XIAO_BLE 위키에 같은 증상과 해결법이 있다: "the Serial function may not compile. The solution is to add the line `#include <Adafruit_TinyUSB.h>`"
- `src/keyring_xiao/main.cpp`에 `#include <Adafruit_TinyUSB.h>` 추가 → 빌드 성공.

## 4. 빌드·테스트 결과 (확인)

| 명령 | 결과 |
|---|---|
| `pio run -e keyring` | SUCCESS (기존과 동일) |
| `pio run -e roadside` | SUCCESS (기존과 동일) |
| `pio run -e keyring_xiao` | SUCCESS, RAM 3.0% (7140 B), Flash 5.9% (48200 B) |
| `./scripts/lab.sh test` | 88 checks, 0 failures |
| `./scripts/test_lab.sh` | 27 passed, 0 failed |
| `./scripts/lab.sh doctor` | 도구 준비됨 |

현재 `keyring_xiao` 펌웨어는 1단계 시험용이다: 부팅 시 `[KEYRING] xiao boot id=1`, 이후 약 10초마다 `[ALIVE] keyring id=1 t=..ms`. BLE 코드 없음. USB 시리얼은 최대 2초만 기다린다(USB 없이 켜도 멈추지 않게).

## 5. 보드 모델 확인 (진행 중)

주문 제품: XIAO nRF52840 **일반형**. 그러나 USB에는 다음과 같이 보인다(확인):

```
/dev/cu.usbmodem1101  VID:PID=2886:8045  SER=4D2ACD3EE254E9D8
USB Product Name = "Seeed XIAO nRF52840 Sense", USB Vendor Name = "Arduino"
```

이 값이 모델의 근거가 아닌 이유:
- USB 이름·PID는 **보드에 지금 들어 있는 펌웨어**가 보고하는 값이다.
- 설치된 플랫폼의 보드 정의(확인): Adafruit 계열 일반형 = `0x8044`, Sense = `0x8045`. 그런데 **mbed 계열은 일반형(`seeed-xiao-mbed-nrf52840`)도 `0x8045`**. 즉 0x8045는 하드웨어가 Sense라는 증거가 아니다.

공식 자료로 확인한 차이 (wiki.seeedstudio.com/XIAO_BLE, 공식 핀맵 이미지):
- Sense에만 6축 IMU(LSM6DS3TR-C)와 PDM 마이크가 있다. 일반형 사양표의 "Built-in Sensors" = N/A.
- 앞면 금속 실드 인쇄는 두 모델 모두 `Model: XIAO-nRF52840` → **실드 글자로는 구분 불가**.
- 뒷면은 두 모델 공식 이미지가 같다(`XIAO nRF52840 v1.0`, BAT+/BAT− 패드) → 뒷면으로는 구분 불가.
- **구분 위치: 앞면 아래쪽 가장자리(USB-C 반대쪽), 오른쪽(D7 패드 아래) 구석**
  - 일반형: 빈 금도금 패드 6개(2열×3)가 드러나 있다 — 부품 미실장 자리
  - Sense: 그 자리에 검은 사각 부품(윗면에 작은 둥근 구멍 = 소리 구멍)이 있다. 공식 핀맵에서 `Microphone`, `PDM_CLK`, `PDM_DATA` 지시선이 이 부품을 가리킨다
- IMU는 공식 이미지에서 지시선이 실드 위를 가리켜 육안 위치를 특정할 수 없다 → 마이크 실장 여부로 판단한다.

판단 기준: 앞면 오른쪽 아래 구석에 소리 구멍 있는 검은 부품 → Sense / 빈 패드 6개 → 일반형.
확인 결과: ______ (사진: ______)

모델별 사용할 보드 설정 (설치된 플랫폼에 둘 다 있음, 확인):

| 모델 | board | 비고 |
|---|---|---|
| 일반형 | `seeed-xiao-afruitnrf52-nrf52840` | 현재 설정 |
| Sense | `seeed-xiao-afruitnrf52-nrf52840-sense` | 같은 Adafruit 계열 core·SoftDevice. 모델 확인 후에만 변경 |

## 6. 업로드 원칙

- 업로드 직전에 포트를 다시 확인하고 대상 보드·펌웨어·환경·명령을 표시한 뒤 승인받는다.
- `nrfutil` 업로드는 애플리케이션 영역만 쓴다. 부트로더 교체·전체 플래시 초기화는 하지 않는다.
- `./scripts/lab.sh upload keyring`은 ESP32용이다. XIAO에 쓰지 않는다.

## 7. 남은 위험

- GCC 10.3.1 사용에 따른 런타임 차이 (미검증)
- 프레임워크 tarball 버전 미고정
- ESP32 ↔ ESP32 실물 BLE 시험도 한 번도 하지 않았다(README) → Phase 4에서 실패하면 송신·수신 어느 쪽 문제인지 따로 확인해야 한다
- 실제 로그 순서는 `[LED] ON` → `[RX] ...` → `[STATE] WAITING -> WARNING` (`setState()`가 출력보다 먼저 실행됨)
