// 경고 판단 로직 — BLE·GPIO와 분리돼 있어 맥북에서 단독으로 테스트할 수 있다.
//
//   WAITING --(유효 키링 신호)--> WARNING
//   WARNING --(마지막 수신 후 timeout 이상 신호 없음)--> WAITING
//
// 출력(LED)은 상태가 실제로 바뀔 때만 OutputSink::apply()로 한 번 전달한다.
// 시간은 Arduino millis()와 같은 단조 증가 ms 값을 받는다. 부호 없는 뺄셈으로
// 경과 시간을 계산하므로 약 49.7일 뒤 millis()가 0으로 돌아가도 동작한다.
#pragma once

#include <stddef.h>
#include <stdint.h>

enum class WarningState { Waiting, Warning };

const char* toString(WarningState state);

// 경고 출력 장치. 펌웨어에서는 GPIO LED, 테스트에서는 호출을 기록하는 가짜 객체.
class OutputSink {
 public:
  virtual ~OutputSink() {}
  virtual void apply(WarningState state) = 0;
};

struct AdvertisementResult {
  bool isKeyring;      // 우리 키링 형식인가
  uint8_t keyringId;   // isKeyring일 때만 의미 있음
  bool stateChanged;   // 이 신호로 WAITING -> WARNING이 됐는가
};

class WarningController {
 public:
  WarningController(uint32_t signalTimeoutMs, OutputSink& output);

  // 수신한 광고의 Manufacturer Data를 넘긴다. 키링 형식이 아니면 무시한다.
  AdvertisementResult onAdvertisement(const uint8_t* data, size_t length,
                                      uint32_t nowMs);

  // 주기적으로 호출. 신호가 timeout 이상 없으면 WAITING으로 바꾼다.
  // 상태가 바뀌었으면 true.
  bool update(uint32_t nowMs);

  WarningState state() const { return state_; }
  uint32_t lastSeenMs() const { return lastSeenMs_; }

 private:
  void setState(WarningState next);

  const uint32_t signalTimeoutMs_;
  OutputSink& output_;
  WarningState state_ = WarningState::Waiting;
  uint32_t lastSeenMs_ = 0;
};
