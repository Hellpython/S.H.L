#include "keyring_packet.h"

namespace keyring {

namespace {
const uint8_t kHeader[] = {0xFF, 0xFF, 'C', 'S', kFormatVersion};
const size_t kHeaderLength = sizeof(kHeader);
}  // namespace

bool buildPayload(uint8_t id, uint8_t out[kPayloadLength]) {
  if (id < kMinId || id > kMaxId) return false;
  for (size_t i = 0; i < kHeaderLength; ++i) out[i] = kHeader[i];
  out[kHeaderLength] = id;
  return true;
}

bool parsePayload(const uint8_t* data, size_t length, uint8_t* outId) {
  if (data == nullptr || length != kPayloadLength) return false;
  for (size_t i = 0; i < kHeaderLength; ++i) {
    if (data[i] != kHeader[i]) return false;
  }
  uint8_t id = data[kHeaderLength];
  if (id < kMinId || id > kMaxId) return false;
  if (outId != nullptr) *outId = id;
  return true;
}

}  // namespace keyring
