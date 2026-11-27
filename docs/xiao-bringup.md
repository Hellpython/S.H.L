# XIAO nRF52840 키링 전환 기록

키링(송신)을 ESP32에서 Seeed Studio XIAO nRF52840으로 바꾸는 작업의 진행 기록.
기존 `keyring`(ESP32 키링), `roadside`(ESP32 도로변) 환경은 그대로 두고 `keyring_xiao` 환경을 추가했다.

표기: **확인** = 이 기록에 적힌 명령으로 실제 실행해 본 결과 / **미검증** = 아직 실행하지 않음

## 1. 현재 단계 (2026-11-27)

| 단계 | 상태 |
|---|---|
| Phase 0 기준선 (기존 빌드·테스트) | 확인 |
| Phase 1 `keyring_xiao` 환경 + 최소 시리얼 펌웨어 빌드 | 확인 (빌드만) |
| 보드 모델 확인 (일반형 / Sense) | **Sense로 잠정 판단** (사용자 육안: 앞면 오른쪽 아래 마이크 부품). 사진·부품 표기 대조 기록은 미완료 |
| Phase 2 USB 업로드 | 실패 2회 후 **3회째 성공** (7절, nrfutil `Device programmed.`) |
| Phase 2 시리얼 로그 | **확인** (`[ALIVE] keyring id=1`) |
| Phase 2 USB 재연결 후 실행 | **확인** (7절) |
| ESP32 업로드 도구(esptool) | **동작 안 함** — `intelhex` 없음 (9절) |
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
| 보드 | `seeed-xiao-afruitnrf52-nrf52840-sense` (Adafruit 계열 core). 커밋 `019513f`까지는 일반형 `seeed-xiao-afruitnrf52-nrf52840` |
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
확인 결과 (2026-11-27): 사용자가 실물 앞면 오른쪽 아래에서 작은 마이크 부품을 확인 → **Sense로 잠정 판단**.
주문 내역(일반형)과 다르다. 실물 사진·부품 표기와 공식 이미지 대조 기록: ______ (미완료)
→ 사용자 지시로 board를 `seeed-xiao-afruitnrf52-nrf52840-sense`로 변경. Sense 보드 정의의 hwid(0x8045)와 현재 USB PID가 일치.
마이크·IMU는 사용하지 않으며 센서 코드는 추가하지 않는다.

모델별 사용할 보드 설정 (설치된 플랫폼에 둘 다 있음, 확인):

| 모델 | board | 비고 |
|---|---|---|
| 일반형 | `seeed-xiao-afruitnrf52-nrf52840` | 현재 설정 |
| Sense | `seeed-xiao-afruitnrf52-nrf52840-sense` | 같은 Adafruit 계열 core·SoftDevice. 모델 확인 후에만 변경 |

## 6. 업로드 원칙

- 업로드 직전에 포트를 다시 확인하고 대상 보드·펌웨어·환경·명령을 표시한 뒤 승인받는다.
- `nrfutil` 업로드는 애플리케이션 영역만 쓴다. 부트로더 교체·전체 플래시 초기화는 하지 않는다.
- `./scripts/lab.sh upload keyring`은 ESP32용이다. XIAO에 쓰지 않는다.

## 7. 업로드 시도 기록 (2026-11-27)

공통: 보드 설정 Sense 변경 후 `keyring`·`roadside`·`keyring_xiao` 빌드 SUCCESS (XIAO RAM 3.0%, Flash 5.9%), 단위 테스트 88/0, `test_lab.sh` 27/0.
업로드 전 포트 재확인: `/dev/cu.usbmodem1101`, VID:PID 2886:8045, SER 4D2ACD3EE254E9D8, 점유 프로세스 없음.
명령: `~/.platformio/penv/bin/pio run -e keyring_xiao -t upload --upload-port /dev/cu.usbmodem1101`

### 시도 1 — 보드에 닿기 전 실패 (rc=1)

```
Tool Manager: Installing https://github.com/pioarduino/esptool/releases/download/v5.1.2/esptool.zip
FileNotFoundError: [Errno 2] No such file or directory: 'package-postinstall.py'
```

- 원인: PlatformIO core는 `upload` 타깃에서 플랫폼의 `type: uploader` 패키지를 모두 필수로 바꾼다(`platformio/platform/base.py`). Seeed 플랫폼은 nRF 보드에도 ESP32용 `tool-esptoolpy`(pioarduino 5.1.2)를 uploader로 선언한다 → nRF 업로드인데 esptool을 설치하려다 그 패키지의 postinstall에서 실패.
- **부작용**: 공용 `~/.platformio/packages/tool-esptoolpy`(espressif32 6.13.0이 쓰는 `~2.41100.0`, esptool 4.11.0)가 pioarduino 5.1.2로 대체됐다.
- 복구 (자동, 확인): 다음 `pio run -e keyring -e roadside`에서 PlatformIO가 `tool-esptoolpy@2.41100.260830`(4.11.0)을 다시 설치하고 5.1.2는 `tool-esptoolpy@src-…`로 옮겨졌다. ESP32 빌드 2종 SUCCESS.
- 남은 확인: ESP32 실제 업로드(`lab.sh upload`)가 4.11.0을 쓰는지는 **미검증**. ESP32 업로드 전에 `ls ~/.platformio/packages | grep esptool`과 업로드 로그의 esptool 버전을 확인할 것.

### 시도 2 — 부트로더 응답 없음 (PlatformIO는 SUCCESS로 보고)

```
Forcing reset using 1200bps open/close on port /dev/cu.usbmodem1101
Waiting for the new upload port...
Uploading .pio/build/keyring_xiao/firmware.zip
Timed out waiting for acknowledgement from device.
Failed to upgrade target. Error is: No data received on serial port. Not able to proceed.
...
keyring_xiao   SUCCESS
```

- **PlatformIO 종료 코드 0, `SUCCESS` 표시였지만 실제 업로드는 실패.** 이 환경에서 업로드 성공은 종료 코드가 아니라 nrfutil 출력(`Device programmed`류)과 이후 시리얼 로그로 판단해야 한다.
- 시도 후 보드는 이전과 같은 USB(PID 0x8045, "Seeed XIAO nRF52840 Sense")로 돌아왔다 → 기존 펌웨어가 계속 실행 중, 덮어쓰지 않음.
- 추정 원인(미확인): 기존 펌웨어가 1200bps 터치로 부트로더에 들어가지 않았거나, 진입 타이밍 문제.
- 다음 조치: Seeed 공식 방법(RESET 버튼 빠르게 2회)으로 부트로더 진입 → USB PID(0x0045 예상)와 UF2 드라이브 `INFO_UF2.TXT` 확인 → 같은 명령으로 재시도. 부트로더 교체·플래시 초기화는 하지 않는다.

### 부트로더 확인 (사용자: USB 재연결 후 RESET 빠르게 2회)

```
USB: VID:PID 2886:0045, Product "XIAO nRF52840 Sense", Vendor "Seeed", SER C41C05879D66124D, /dev/cu.usbmodem1101
/Volumes/XIAO-SENSE/INFO_UF2.TXT:
UF2 Bootloader 0.6.1 lib/nrfx (v2.0.0) lib/tinyusb (0.10.1-293-gaf8e5a90) lib/uf2 (remotes/origin/configupdate-9-gadbb8c7)
Model: Seeed XIAO nRF52840
Board-ID: Seeed_XIAO_nRF52840_Sense
SoftDevice: S140 version 7.3.0
Date: Nov 12 2021
```

- Board-ID `Seeed_XIAO_nRF52840_Sense`, 부트로더 0.6.1 + S140 7.3.0 → Seeed 위키의 Sense 부트로더 파일명(`Seeed_XIAO_nRF52840_Sense_bootloader-0.6.1_s140_7.3.0.hex`)과 일치. 보드 정의의 SoftDevice(7.3.0)와도 일치.
- 육안(마이크 부품) + 부트로더 Board-ID → Sense 판단 근거 2개. 부트로더 문자열도 공장에서 쓴 소프트웨어 값이므로 하드웨어 단독 증거는 아니다.
- UF2 드라이브에는 아무것도 복사하지 않았다.

### 시도 3 — 성공 (nrfutil 직접 실행, 1200bps 터치 생략)

이미 부트로더 모드라 PIO 업로드의 1200bps 터치(`BeforeUpload`) 단계만 빼고 PIO와 같은 명령을 실행했다(`nrf_build.py`의 `UPLOADCMD`).
빌드 산출물이 Sense 설정인지 확인: `SEEED_XIAO_NRF52840_SENSE` 정의 포함.

```
$ ~/.platformio/penv/bin/python ~/.platformio/packages/tool-adafruit-nrfutil/adafruit-nrfutil.py \
    dfu serial -p /dev/cu.usbmodem1101 -b 115200 --singlebank -pkg .pio/build/keyring_xiao/firmware.zip
Upgrading target on /dev/cu.usbmodem1101 with DFU package ... Flow control is disabled, Single bank, Touch disabled
...
Activating new firmware
Device programmed.
(rc=0)
```

업로드 후 (확인):
- USB: VID:PID 2886:8045, Product `XIAO nRF52840 Sense` (이전 펌웨어의 "Seeed XIAO nRF52840 Sense"/Vendor "Arduino"와 다름 = 새 펌웨어의 보드 정의 `usb_product`)
- 시리얼 (부팅 22초 뒤 포트를 열어 부팅 메시지는 놓침):

```
19:26:05 [ALIVE] keyring id=1 t=22001ms
19:26:15 [ALIVE] keyring id=1 t=32001ms
```

USB 재연결 후 (확인, RESET 버튼 없이 케이블만 분리·재연결):

```
19:28:28 port gone (unplugged)
19:28:31 port back: /dev/cu.usbmodem1101
19:28:41 [ALIVE] keyring id=1 t=10527ms
19:28:51 [ALIVE] keyring id=1 t=20527ms
```

- 보드 시각이 다시 0부터 → 전원 재인가 후 새 펌웨어로 부팅. USB 2886:8045 "XIAO nRF52840 Sense".
- 부팅 메시지 `[KEYRING] xiao boot`는 두 번 다 못 봤다. 펌웨어가 USB 시리얼 연결을 최대 2초만 기다리고, 그 안에 호스트가 포트를 열지 않으면 출력이 버려진다(USB 없이 켜도 멈추지 않게 한 의도된 동작). 부팅 확인은 `[ALIVE]`의 `t=` 값으로 한다.

## 8. 남은 위험

- GCC 10.3.1 사용에 따른 런타임 차이 (미검증)
- 프레임워크 tarball 버전 미고정
- ESP32 ↔ ESP32 실물 BLE 시험도 한 번도 하지 않았다(README) → Phase 4에서 실패하면 송신·수신 어느 쪽 문제인지 따로 확인해야 한다
- 실제 로그 순서는 `[LED] ON` → `[RX] ...` → `[STATE] WAITING -> WARNING` (`setState()`가 출력보다 먼저 실행됨)

## 9. ESP32 업로드 도구 상태 (esptool)

7절 시도 1에서 공용 `tool-esptoolpy`가 교체되었다가 자동 재설치됐다. 빌드 성공만으로는 업로드 도구를 확인할 수 없어(빌드가 이전 `firmware.bin`을 재사용, esptool 미실행) 존재하지 않는 포트로 ESP32 업로드 경로를 실행해 봤다.

```
$ pio run -e keyring -t upload --upload-port /dev/cu.nonexistent-selftest -v
"/Users/heechan/.platformio/penv/bin/python" ".../packages/tool-esptoolpy/esptool.py" --chip esp32 --port "/dev/cu.nonexistent-selftest" ...
  File ".../tool-esptoolpy/esptool/bin_image.py", line 16, in <module>
    from intelhex import HexRecordError, IntelHex
ModuleNotFoundError: No module named 'intelhex'
*** [upload] Error 1
```

- 선택된 도구는 맞다: `tool-esptoolpy @ 2.41100.260830 (4.11.0)`.
- 그러나 실행 불가: 이 패키지의 postinstall(`package-postinstall.py`)이 의존성 5개(cryptography, ecdsa, bitstring, reedsolo, intelhex)를 `tool-esptoolpy/_contrib`에 설치해야 하는데 `_contrib`이 없다 → 재설치 때 postinstall이 실행되지 않았거나 실패.
- **사건 이전 원래 설치본에 `_contrib`이 있었는지는 기록이 없어 알 수 없다**(ESP32 실제 업로드는 한 번도 하지 않음). 따라서 "이번 사건으로 손상"인지 "원래부터 동작 안 함"인지 단정하지 않는다.
- 결론: **현재 ESP32 업로드(`lab.sh upload`)는 esptool 시작 단계에서 실패한다.** 복구 전 ESP32에 업로드하지 않는다.
- 복구 후보(사용자 승인 대기): `pio pkg install -g -t "platformio/tool-esptoolpy@2.41100.260830" -f` → 같은 가짜 포트 시험에서 `intelhex` 오류 없이 포트 열기 단계에서 실패하는지 확인.
- 재발 위험: Seeed 플랫폼이 nRF 업로드에도 pioarduino `tool-esptoolpy`를 uploader로 선언 → `pio run -e keyring_xiao -t upload`가 같은 이름 패키지를 다시 건드릴 수 있다. XIAO 업로드 전후에 `ls ~/.platformio/packages | grep esptool`로 확인한다.
