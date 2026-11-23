// 도로변 장치(수신 + LED) 펌웨어
//
// loop() 한 바퀴:
//   1) kScanDurationSec 동안 BLE 스캔 (스캔이 끝날 때까지 대기)
//   2) 스캔 결과 중 키링 형식만 경고 판단 로직에 전달, RSSI 로그 출력
//      스캔 시작이 실패하면 [SCAN ERROR] 로그만 남기고 결과 처리는 건너뜀
//   3) 타임아웃 확인 -> 상태가 바뀌었을 때만 LED 갱신
//
// 스캔 결과 처리와 판단은 모두 loop()에서 한다. BLE 태스크와 공유하는 것은
// "스캔 끝남" 플래그(atomic) 하나뿐이다.
// RSSI는 기록만 한다. 거리 값으로 쓰지 않는다.
//
// 스캔 실패 시 경고 상태: 실패한 회차는 "새 키링 신호 없음"과 같게 취급되어
// update()가 그대로 실행된다. 즉 실패가 타임아웃 이상 계속되면 WARNING이
// WAITING으로 바뀌고 LED가 꺼진다. 실패 시 LED 정책(예: 고장 표시)은
// 안전 요구사항이 정해지지 않아 정하지 않았다.
#include <Arduino.h>
#include <BLEDevice.h>

#include <atomic>

#include "app_config.h"
#include "warning_controller.h"

class GpioLed : public OutputSink {
 public:
  explicit GpioLed(uint8_t pin) : pin_(pin) {}

  void begin() {
    pinMode(pin_, OUTPUT);
    digitalWrite(pin_, LOW);
  }

  void apply(WarningState state) override {
    digitalWrite(pin_, state == WarningState::Warning ? HIGH : LOW);
    Serial.printf("[LED] %s\n", state == WarningState::Warning ? "ON" : "OFF");
  }

 private:
  const uint8_t pin_;
};

static GpioLed led(config::kLedPin);
static WarningController controller(config::kSignalTimeoutMs, led);
static BLEScan* scan = nullptr;
static std::atomic<bool> scanFinished(false);
static uint32_t scanErrorCount = 0;
static uint32_t scanOkCount = 0;
static uint32_t lastHeartbeatMs = 0;

// 스캔 시간이 끝나면 BLE 태스크에서 호출된다. 플래그만 세운다.
static void onScanFinished(BLEScanResults) { scanFinished = true; }

// 스캔 1회를 끝까지 기다린다. 라이브러리가 스캔 시작 오류를 반환하면 false.
// (오류 상세는 라이브러리가 "[E] esp_ble_gap_..." 형식으로 먼저 출력한다.)
// 시작 명령이 받아들여진 뒤 비동기로 오는 실패는 BLEScan이 처리하지 않아
// 여기서는 감지하지 않는다(BLEDevice::setCustomGapHandler로 가능, 미구현).
static bool runScan() {
  scanFinished = false;
  if (!scan->start(config::kScanDurationSec, onScanFinished, false)) {
    return false;
  }
  while (!scanFinished) delay(10);
  return true;
}

void setup() {
  Serial.begin(115200);
  led.begin();

  BLEDevice::init("");
  scan = BLEDevice::getScan();
  scan->setActiveScan(false);  // 키링은 스캔 응답이 없으므로 수동 스캔
  scan->setInterval(config::kScanIntervalMs);
  scan->setWindow(config::kScanWindowMs);

  Serial.printf("[ROADSIDE] state=%s timeout=%lums\n",
                toString(controller.state()),
                static_cast<unsigned long>(config::kSignalTimeoutMs));
}

void loop() {
  if (!runScan()) {
    ++scanErrorCount;
    Serial.printf("[SCAN ERROR] t=%lums count=%lu state=%s\n",
                  static_cast<unsigned long>(millis()),
                  static_cast<unsigned long>(scanErrorCount),
                  toString(controller.state()));
    // 실패가 반복될 때 로그가 쏟아지지 않도록 정상 스캔 1회만큼 쉰다.
    delay(config::kScanDurationSec * 1000);
  } else {
    ++scanOkCount;
    BLEScanResults results = scan->getResults();
    uint32_t now = millis();

    for (int i = 0; i < results.getCount(); ++i) {
      BLEAdvertisedDevice device = results.getDevice(i);
      if (!device.haveManufacturerData()) continue;

      std::string data = device.getManufacturerData();
      AdvertisementResult r = controller.onAdvertisement(
          reinterpret_cast<const uint8_t*>(data.data()), data.size(), now);
      if (!r.isKeyring) continue;

      Serial.printf("[RX] t=%lums keyring=%u rssi=%d\n",
                    static_cast<unsigned long>(now), r.keyringId,
                    device.getRSSI());
      if (r.stateChanged) {
        Serial.printf("[STATE] WAITING -> WARNING t=%lums\n",
                      static_cast<unsigned long>(now));
      }
    }
    scan->clearResults();  // 결과를 지우지 않으면 메모리가 계속 쌓인다
  }

  // t는 보드 시각. 마지막 [RX] t와의 차이로 경고 종료까지 걸린 시간을 잰다.
  uint32_t updateMs = millis();
  if (controller.update(updateMs)) {
    Serial.printf("[STATE] WARNING -> WAITING t=%lums\n",
                  static_cast<unsigned long>(updateMs));
  }

  // 생존 로그: 스캔 루프가 돌고 있다는 표시. 끊기면 스캔 정지를 의심한다.
  uint32_t nowMs = millis();
  if (nowMs - lastHeartbeatMs >= config::kHeartbeatIntervalMs) {
    lastHeartbeatMs = nowMs;
    Serial.printf("[ALIVE] roadside t=%lums scans_ok=%lu scan_errors=%lu state=%s\n",
                  static_cast<unsigned long>(nowMs),
                  static_cast<unsigned long>(scanOkCount),
                  static_cast<unsigned long>(scanErrorCount),
                  toString(controller.state()));
  }
}
