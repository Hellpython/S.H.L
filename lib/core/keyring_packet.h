// 키링 BLE 광고 데이터 형식 (Manufacturer Specific Data, AD type 0xFF)
//
//  byte  0-1 : Company ID 0xFFFF (little-endian) — Bluetooth SIG가 "테스트용"으로
//              남겨 둔 값. 실제 제품에는 쓸 수 없다(배포 전 교체 필요).
//  byte  2-3 : 'C' 'S'  프로젝트 표식 (Child Safety)
//  byte  4   : 형식 버전 (현재 1)
//  byte  5   : 키링 번호 1~254 (0, 255는 사용 안 함)
//
// 이름·학교·연락처 등은 넣지 않는다. 다만 키링 번호는 고정값이라
// (BLE 주소와 함께) 같은 키링을 반복 관측해 추적하는 데 쓰일 수 있다.
// 추적 위험 완화는 이 프로토타입 범위 밖이다(연구실 시험 전용).
//
// 주의: 이 표식은 "우리 형식인지" 구분하는 용도이지 인증이 아니다.
// 누구나 같은 바이트를 광고하면 키링으로 인식된다(위조 가능).
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace keyring {

const uint8_t kPayloadLength = 6;
const uint8_t kFormatVersion = 1;
const uint8_t kMinId = 1;
const uint8_t kMaxId = 254;

// id가 범위를 벗어나면 false. 성공하면 out[0..5]에 기록한다.
bool buildPayload(uint8_t id, uint8_t out[kPayloadLength]);

// data가 키링 형식이면 true와 함께 *outId에 키링 번호를 넣는다.
// 길이·Company ID·표식·버전·번호 범위 중 하나라도 다르면 false.
bool parsePayload(const uint8_t* data, size_t length, uint8_t* outId);

}  // namespace keyring
