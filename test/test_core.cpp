// 맥북에서 실행하는 단위 테스트 (가짜 BLE 이벤트 + 가짜 LED).
// 실제 ESP32/BLE 하드웨어는 전혀 사용하지 않는다.
// 실행: ./scripts/run_tests.sh
#include <cstdio>
#include <vector>

#include "keyring_packet.h"
#include "warning_controller.h"

static int g_failures = 0;
static int g_checks = 0;

#define CHECK(cond)                                                \
  do {                                                             \
    ++g_checks;                                                    \
    if (!(cond)) {                                                 \
      ++g_failures;                                                \
      std::printf("  FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); \
    }                                                              \
  } while (0)

// LED 대신 출력 명령을 기록하는 가짜 객체
class FakeOutput : public OutputSink {
 public:
  void apply(WarningState state) override { commands.push_back(state); }
  std::vector<WarningState> commands;
};

static const uint32_t kTimeout = 3000;  // 테스트용 값

static std::vector<uint8_t> validPayload(uint8_t id) {
  std::vector<uint8_t> p(keyring::kPayloadLength);
  keyring::buildPayload(id, p.data());
  return p;
}

static AdvertisementResult send(WarningController& c,
                                const std::vector<uint8_t>& p, uint32_t now) {
  return c.onAdvertisement(p.data(), p.size(), now);
}

// ---- 광고 데이터 형식 ----

static void test_payload_roundtrip() {
  uint8_t buf[keyring::kPayloadLength];
  CHECK(keyring::buildPayload(7, buf));
  uint8_t id = 0;
  CHECK(keyring::parsePayload(buf, sizeof(buf), &id));
  CHECK(id == 7);
}

static void test_payload_rejects_out_of_range_id() {
  uint8_t buf[keyring::kPayloadLength];
  CHECK(!keyring::buildPayload(0, buf));
  CHECK(!keyring::buildPayload(255, buf));
  CHECK(keyring::buildPayload(1, buf));
  CHECK(keyring::buildPayload(254, buf));
}

static void test_payload_rejects_malformed() {
  std::vector<uint8_t> ok = validPayload(3);
  uint8_t id = 0;

  CHECK(!keyring::parsePayload(nullptr, 6, &id));
  CHECK(!keyring::parsePayload(ok.data(), 0, &id));
  CHECK(!keyring::parsePayload(ok.data(), 5, &id));  // 짧음

  std::vector<uint8_t> longer = ok;
  longer.push_back(0);
  CHECK(!keyring::parsePayload(longer.data(), longer.size(), &id));  // 김

  for (size_t i = 0; i < ok.size(); ++i) {  // 한 바이트만 달라도 거부
    std::vector<uint8_t> bad = ok;
    bad[i] = (i == 5) ? 0 : static_cast<uint8_t>(bad[i] ^ 0x01);
    CHECK(!keyring::parsePayload(bad.data(), bad.size(), &id));
  }
}

// ---- 지시서 테스트 항목 1~7 ----

// 1. 정상 키링 신호 수신
static void test_1_valid_keyring_starts_warning() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  CHECK(c.state() == WarningState::Waiting);

  AdvertisementResult r = send(c, validPayload(1), 1000);
  CHECK(r.isKeyring);
  CHECK(r.keyringId == 1);
  CHECK(r.stateChanged);
  CHECK(c.state() == WarningState::Warning);
  CHECK(c.lastSeenMs() == 1000);
  CHECK(out.commands.size() == 1);
  CHECK(out.commands[0] == WarningState::Warning);
}

// 2. 다른 장치의 신호 수신
static void test_2_other_device_is_ignored() {
  FakeOutput out;
  WarningController c(kTimeout, out);

  const uint8_t apple[] = {0x4C, 0x00, 0x02, 0x15, 0x01, 0x02};  // 다른 회사 ID
  const uint8_t empty[] = {0};
  AdvertisementResult r = c.onAdvertisement(apple, sizeof(apple), 1000);
  CHECK(!r.isKeyring);
  CHECK(!r.stateChanged);
  c.onAdvertisement(empty, 0, 1000);  // Manufacturer Data 없음
  c.onAdvertisement(nullptr, 0, 1000);

  CHECK(c.state() == WarningState::Waiting);
  CHECK(out.commands.empty());
}

// 2-보충. 경고 중 다른 장치 신호는 마지막 수신 시각을 연장하지 않는다
static void test_2b_other_device_does_not_extend_warning() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  send(c, validPayload(1), 1000);

  const uint8_t other[] = {0x4C, 0x00, 'C', 'S', 1, 1};
  c.onAdvertisement(other, sizeof(other), 3500);
  CHECK(c.lastSeenMs() == 1000);
  CHECK(c.update(4000));  // 1000 + 3000
  CHECK(c.state() == WarningState::Waiting);
}

// 3. 신호 연속 수신 — 경고 유지, 마지막 수신 시각 갱신, LED 명령은 1번만
static void test_3_continuous_signal_keeps_warning() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  for (uint32_t t = 0; t <= 10000; t += 500) {
    send(c, validPayload(1), t);
    CHECK(!c.update(t));
  }
  CHECK(c.state() == WarningState::Warning);
  CHECK(c.lastSeenMs() == 10000);
  CHECK(out.commands.size() == 1);
}

// 4. 신호 소실에 따른 경고 종료
static void test_4_signal_loss_ends_warning() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  send(c, validPayload(1), 1000);

  CHECK(!c.update(2000));
  CHECK(c.update(5000));
  CHECK(c.state() == WarningState::Waiting);
  CHECK(!c.update(9000));  // 이미 WAITING이면 다시 명령하지 않음
  CHECK(out.commands.size() == 2);
  CHECK(out.commands[1] == WarningState::Waiting);
}

// 5. 경고 종료 후 재수신
static void test_5_reacquire_after_end() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  send(c, validPayload(1), 1000);
  c.update(4000);
  CHECK(c.state() == WarningState::Waiting);

  AdvertisementResult r = send(c, validPayload(2), 6000);
  CHECK(r.stateChanged);
  CHECK(r.keyringId == 2);
  CHECK(c.state() == WarningState::Warning);
  CHECK(c.lastSeenMs() == 6000);
  CHECK(out.commands.size() == 3);
  CHECK(out.commands[2] == WarningState::Warning);
}

// 6. 수신 이벤트 중복 발생 (같은 시각 / 같은 키링 여러 번)
static void test_6_duplicate_events() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  AdvertisementResult first = send(c, validPayload(1), 1000);
  AdvertisementResult dup1 = send(c, validPayload(1), 1000);
  AdvertisementResult dup2 = send(c, validPayload(1), 1000);
  CHECK(first.stateChanged);
  CHECK(!dup1.stateChanged);
  CHECK(!dup2.stateChanged);
  CHECK(dup1.isKeyring && dup2.isKeyring);
  CHECK(out.commands.size() == 1);
}

// 7. 시간 경계 조건
static void test_7a_exact_timeout_boundary() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  send(c, validPayload(1), 1000);
  CHECK(!c.update(1000 + kTimeout - 1));  // 2999ms 경과: 유지
  CHECK(c.state() == WarningState::Warning);
  CHECK(c.update(1000 + kTimeout));       // 정확히 3000ms 경과: 종료
  CHECK(c.state() == WarningState::Waiting);
}

static void test_7b_signal_just_before_timeout_extends() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  send(c, validPayload(1), 1000);
  send(c, validPayload(1), 1000 + kTimeout - 1);   // 끝나기 1ms 전 재수신
  CHECK(!c.update(1000 + kTimeout));
  CHECK(!c.update(1000 + 2 * kTimeout - 2));
  CHECK(c.update(1000 + 2 * kTimeout - 1));
  CHECK(out.commands.size() == 2);
}

static void test_7c_millis_wraparound() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  const uint32_t nearMax = 0xFFFFFFFFu - 1000;  // millis() 약 49.7일 지점
  send(c, validPayload(1), nearMax);
  CHECK(!c.update(nearMax + 1500));  // 0으로 넘어간 뒤 경과 1500ms
  CHECK(c.state() == WarningState::Warning);
  CHECK(c.update(nearMax + kTimeout));  // 넘어간 뒤 경과 3000ms
}

static void test_7d_signal_at_time_zero() {
  FakeOutput out;
  WarningController c(kTimeout, out);
  send(c, validPayload(1), 0);  // 부팅 직후 수신
  CHECK(c.state() == WarningState::Warning);
  CHECK(!c.update(kTimeout - 1));
  CHECK(c.update(kTimeout));
}

int main() {
  struct Case {
    const char* name;
    void (*fn)();
  } cases[] = {
      {"payload_roundtrip", test_payload_roundtrip},
      {"payload_rejects_out_of_range_id", test_payload_rejects_out_of_range_id},
      {"payload_rejects_malformed", test_payload_rejects_malformed},
      {"1_valid_keyring_starts_warning", test_1_valid_keyring_starts_warning},
      {"2_other_device_is_ignored", test_2_other_device_is_ignored},
      {"2b_other_device_does_not_extend_warning",
       test_2b_other_device_does_not_extend_warning},
      {"3_continuous_signal_keeps_warning", test_3_continuous_signal_keeps_warning},
      {"4_signal_loss_ends_warning", test_4_signal_loss_ends_warning},
      {"5_reacquire_after_end", test_5_reacquire_after_end},
      {"6_duplicate_events", test_6_duplicate_events},
      {"7a_exact_timeout_boundary", test_7a_exact_timeout_boundary},
      {"7b_signal_just_before_timeout_extends",
       test_7b_signal_just_before_timeout_extends},
      {"7c_millis_wraparound", test_7c_millis_wraparound},
      {"7d_signal_at_time_zero", test_7d_signal_at_time_zero},
  };

  for (const Case& tc : cases) {
    int before = g_failures;
    tc.fn();
    std::printf("%s %s\n", g_failures == before ? "PASS" : "FAIL", tc.name);
  }
  std::printf("\n%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
