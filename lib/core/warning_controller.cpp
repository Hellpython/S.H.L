#include "warning_controller.h"

#include "keyring_packet.h"

const char* toString(WarningState state) {
  return state == WarningState::Warning ? "WARNING" : "WAITING";
}

WarningController::WarningController(uint32_t signalTimeoutMs,
                                     OutputSink& output)
    : signalTimeoutMs_(signalTimeoutMs), output_(output) {}

AdvertisementResult WarningController::onAdvertisement(const uint8_t* data,
                                                       size_t length,
                                                       uint32_t nowMs) {
  AdvertisementResult result = {false, 0, false};
  if (!keyring::parsePayload(data, length, &result.keyringId)) return result;

  result.isKeyring = true;
  lastSeenMs_ = nowMs;
  if (state_ == WarningState::Waiting) {
    setState(WarningState::Warning);
    result.stateChanged = true;
  }
  return result;
}

bool WarningController::update(uint32_t nowMs) {
  if (state_ != WarningState::Warning) return false;
  if (nowMs - lastSeenMs_ < signalTimeoutMs_) return false;
  setState(WarningState::Waiting);
  return true;
}

void WarningController::setState(WarningState next) {
  state_ = next;
  output_.apply(next);
}
