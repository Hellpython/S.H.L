// 어린이 키링(송신) 펌웨어 — Seeed XIAO nRF52840
// 연결 없이 키링 형식의 BLE 광고만 일정 주기로 반복 송출한다.
// 광고 데이터는 ESP32 키링(src/keyring)과 같은 6바이트 Manufacturer Data.
#include <Arduino.h>
// USB 시리얼(Serial) 구현. 빠지면 링크 오류가 난다(Seeed XIAO_BLE 위키 안내).
#include <Adafruit_TinyUSB.h>
#include <bluefruit.h>

#include "app_config.h"
#include "keyring_packet.h"

static void halt(const char* message) {
  Serial.println(message);
  while (true) delay(1000);
}

void setup() {
  Serial.begin(115200);
  // USB 시리얼 연결을 최대 2초만 기다린다. 무한 대기하면 USB 없이 켰을 때 멈춘다.
  uint32_t start = millis();
  while (!Serial && millis() - start < 2000) delay(10);

  uint8_t payload[keyring::kPayloadLength];
  if (!keyring::buildPayload(config::kKeyringId, payload)) {
    halt("[ERROR] kKeyringId must be 1..254");
  }

  // 광고 중 보드 LED 자동 점멸을 끈다(불필요한 전력 소모).
  Bluefruit.autoConnLed(false);
  if (!Bluefruit.begin()) halt("[ERROR] Bluefruit.begin failed");

  // 장치 이름은 광고하지 않는다(addName 호출 안 함).
  // addManufacturerData는 받은 바이트를 그대로 넣는다. Company ID(FF FF)는
  // payload 앞 2바이트에 이미 들어 있으므로 중복되지 않는다.
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addManufacturerData(payload, sizeof(payload));
  Bluefruit.Advertising.setType(
      BLE_GAP_ADV_TYPE_NONCONNECTABLE_NONSCANNABLE_UNDIRECTED);  // 연결 불가 광고
  // fast/slow를 같게 둔다. 기본값은 처음 30초만 fast 주기이고 이후 느려진다.
  Bluefruit.Advertising.setIntervalMS(config::kAdvertisingIntervalMs,
                                      config::kAdvertisingIntervalMs);
  // 0 = 시간 제한 없이 계속 광고. 실패는 SoftDevice 오류를 그대로 반영한다.
  if (!Bluefruit.Advertising.start(0)) {
    halt("[ERROR] advertising start failed");
  }

  // 광고 시작 명령이 받아들여졌다는 뜻이다. 실제 송신은 스캐너로 확인한다.
  Serial.printf("[KEYRING] advertising id=%u interval=%ums\n",
                config::kKeyringId, config::kAdvertisingIntervalMs);
}

void loop() {
  // 광고는 SoftDevice가 알아서 반복한다. 여기서는 생존 로그만 찍는다.
  Serial.printf("[ALIVE] keyring id=%u t=%lums\n", config::kKeyringId,
                static_cast<unsigned long>(millis()));
  delay(config::kHeartbeatIntervalMs);
}
