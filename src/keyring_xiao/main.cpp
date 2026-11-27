// 어린이 키링(송신) 펌웨어 — Seeed XIAO nRF52840
// 1단계: 보드 실행 확인용. 시리얼 생존 로그만 찍는다(BLE 없음).
#include <Arduino.h>
// USB 시리얼(Serial) 구현. 빠지면 링크 오류가 난다(Seeed XIAO_BLE 위키 안내).
#include <Adafruit_TinyUSB.h>

#include "app_config.h"

void setup() {
  Serial.begin(115200);
  // USB 시리얼 연결을 최대 2초만 기다린다. 무한 대기하면 USB 없이 켰을 때 멈춘다.
  uint32_t start = millis();
  while (!Serial && millis() - start < 2000) delay(10);

  Serial.printf("[KEYRING] xiao boot id=%u\n", config::kKeyringId);
}

void loop() {
  Serial.printf("[ALIVE] keyring id=%u t=%lums\n", config::kKeyringId,
                static_cast<unsigned long>(millis()));
  delay(config::kHeartbeatIntervalMs);
}
