// 어린이 키링(송신) 펌웨어
// 연결 없이 키링 형식의 BLE 광고만 일정 주기로 반복 송출한다.
#include <Arduino.h>
#include <BLEDevice.h>

#include "app_config.h"
#include "keyring_packet.h"

// BLE 광고 주기 단위는 0.625ms
static uint16_t toAdvertisingUnits(uint16_t ms) { return ms * 1000 / 625; }

void setup() {
  Serial.begin(115200);

  uint8_t payload[keyring::kPayloadLength];
  if (!keyring::buildPayload(config::kKeyringId, payload)) {
    Serial.println("[ERROR] kKeyringId must be 1..254");
    while (true) delay(1000);
  }

  // 장치 이름은 광고하지 않는다(빈 이름).
  BLEDevice::init("");

  BLEAdvertisementData data;
  data.setFlags(0x06);  // LE General Discoverable, BR/EDR 미지원
  data.setManufacturerData(
      std::string(reinterpret_cast<char*>(payload), sizeof(payload)));

  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->setAdvertisementData(data);
  advertising->setScanResponse(false);
  advertising->setAdvertisementType(ADV_TYPE_NONCONN_IND);  // 연결 불가 광고
  uint16_t interval = toAdvertisingUnits(config::kAdvertisingIntervalMs);
  advertising->setMinInterval(interval);
  advertising->setMaxInterval(interval);
  advertising->start();

  Serial.printf("[KEYRING] advertising id=%u interval=%ums\n",
                config::kKeyringId, config::kAdvertisingIntervalMs);
}

void loop() {
  // 광고는 BLE 컨트롤러가 알아서 반복한다. 여기서는 생존 로그만 찍는다
  // (어느 USB 포트가 키링인지 시리얼 모니터로 구분할 때도 쓴다).
  Serial.printf("[ALIVE] keyring id=%u t=%lums\n", config::kKeyringId,
                static_cast<unsigned long>(millis()));
  delay(config::kHeartbeatIntervalMs);
}
