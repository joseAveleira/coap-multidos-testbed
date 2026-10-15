#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace wire {
struct Message {
  uint8_t type = 0, code = 0, tokenLen = 0;
  uint16_t mid = 0;
  const uint8_t* token = nullptr;
  const uint8_t* payload = nullptr;
  size_t payloadLen = 0;
  bool hasBlock = false, hasSize = false;
  uint32_t block = 0, size = 0;
  const uint8_t* etag = nullptr;
  uint8_t etagLen = 0;
};
inline bool extended(uint8_t n, const uint8_t* b, size_t len, size_t& at, uint32_t& out) {
  if (n < 13) { out = n; return true; }
  if (n == 13 && at < len) { out = 13 + b[at++]; return true; }
  if (n == 14 && at + 2 <= len) { out = 269 + (uint32_t(b[at]) << 8) + b[at + 1]; at += 2; return true; }
  return false;
}
inline bool parse(const uint8_t* b, size_t len, Message& m) {
  m = Message{};
  if (len < 4 || b[0] >> 6 != 1 || (b[0] & 15) > 8 || len < size_t(4 + (b[0] & 15))) return false;
  m.type = (b[0] >> 4) & 3; m.code = b[1]; m.mid = (uint16_t(b[2]) << 8) | b[3];
  m.tokenLen = b[0] & 15; m.token = b + 4;
  size_t at = 4 + m.tokenLen; uint32_t number = 0;
  if (!m.code && (m.tokenLen || len != 4)) return false;
  while (at < len) {
    uint8_t h = b[at++];
    if (h == 255) { if (at == len) return false; m.payload = b + at; m.payloadLen = len - at; return true; }
    uint32_t delta, length;
    if (!extended(h >> 4, b, len, at, delta) || !extended(h & 15, b, len, at, length)) return false;
    number += delta;
    if (number > 65535 || length > len - at) return false;
    if ((number & 1) && number != 23) return false; // Unknown critical response option.
    if (number == 23 || number == 28) {
      if (length > (number == 23 ? 3u : 4u)) return false;
      uint32_t value = 0; for (size_t j = 0; j < length; j++) value = (value << 8) | b[at + j];
      if (number == 23) { if (m.hasBlock || (value & 7) > 6) return false; m.hasBlock = true; m.block = value; }
      else { if (m.hasSize) return false; m.hasSize = true; m.size = value; }
    } else if (number == 4) {
      if (m.etag || length == 0 || length > 8) return false;
      m.etag = b + at; m.etagLen = uint8_t(length);
    }
    at += length;
  }
  return true;
}
// Fixed known paths => <= 23 bytes. Caller supplies at least 32 bytes.
inline size_t get(uint8_t* out, bool con, uint16_t mid, uint32_t token,
                  bool large, uint32_t block = 0, uint8_t szx = 6) {
  if (szx > 6 || block > 0xfffff) return 0;
  out[0] = con ? 0x44 : 0x54; out[1] = 1; out[2] = mid >> 8; out[3] = mid & 255;
  for (int i = 0; i < 4; i++) out[4 + i] = (token >> (24 - 8 * i)) & 255;
  const char* path = large ? "large" : "sensor";
  size_t n = strlen(path), at = 8; out[at++] = 0xb0 | n;
  memcpy(out + at, path, n); at += n;
  if (large) {
    const uint32_t value = (block << 4) | szx;
    size_t count = value > 65535 ? 3 : value > 255 ? 2 : value ? 1 : 0;
    out[at++] = 0xc0 | count; // Block2(23) - Uri-Path(11) = 12.
    for (size_t i = 0; i < count; i++) out[at++] = value >> (8 * (count - i - 1));
  }
  return at;
}
inline void ack(uint8_t* out, uint16_t mid) {
  out[0] = 0x60; out[1] = 0; out[2] = mid >> 8; out[3] = mid & 255;
}
}

