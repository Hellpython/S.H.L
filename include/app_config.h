// 설정값 모음. 모든 값은 1차 실험용 초기값이며 안전 성능이 검증된 기준이 아니다.
// 연구실 실측 후 조정한다.
#pragma once

#include <stdint.h>

namespace config {

// ---- 키링(송신) ----
// 키링 번호 1~254. 키링마다 다른 번호로 빌드한다.
const uint8_t kKeyringId = 1;
// 광고 주기(ms). 짧을수록 빨리 감지되지만 배터리를 더 쓴다.
// BLE 4.x 비연결 광고의 최소 주기는 100ms.
const uint16_t kAdvertisingIntervalMs = 100;

// ---- 도로변 장치(수신) ----
// 한 번 스캔하는 시간(초). 스캔이 끝날 때마다 결과를 처리하므로
// 감지·종료 판단이 최대 이 시간만큼 늦어질 수 있다.
const uint32_t kScanDurationSec = 1;
// 스캔 주기·창(ms). 창 <= 주기여야 하고, 같으면 쉬지 않고 수신한다.
const uint16_t kScanIntervalMs = 100;
const uint16_t kScanWindowMs = 99;
// 마지막 키링 수신 후 이 시간(ms) 동안 신호가 없으면 경고 종료.
const uint32_t kSignalTimeoutMs = 3000;
// LED 연결 핀. 실물 보드·LED 확인 전 임시값.
// GPIO23은 부팅 strapping 핀이 아니고 플래시 핀도 아니어서 골랐다.
const uint8_t kLedPin = 23;

// ---- 공통 ----
// 이 간격(ms)마다 시리얼에 생존 로그를 찍는다. 수신기는 키링이 없으면 다른
// 로그가 없으므로, 이 로그가 끊기면 "키링 없음"이 아니라 "장치·스캔 정지"를
// 의심한다. 경고 판단에는 쓰지 않는다.
const uint32_t kHeartbeatIntervalMs = 10000;

// 잘못된 조합은 빌드 단계에서 막는다.
static_assert(kKeyringId >= 1 && kKeyringId <= 254, "kKeyringId: 1..254");
static_assert(kAdvertisingIntervalMs >= 100, "non-connectable min 100ms");
static_assert(kScanWindowMs <= kScanIntervalMs, "scan window <= interval");
static_assert(kScanDurationSec >= 1, "scan duration >= 1s");
static_assert(kHeartbeatIntervalMs > kScanDurationSec * 1000,
              "heartbeat must be longer than one scan");
// 스캔 1회보다 짧으면 한 번의 스캔에서 신호를 놓치기만 해도 경고가 꺼진다.
static_assert(kSignalTimeoutMs > kScanDurationSec * 1000,
              "timeout must be longer than one scan");

}  // namespace config
