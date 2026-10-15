#include "coap_wire.h"
#include <cassert>
#include <cstdio>

int main() {
  uint8_t out[32];
  size_t n = wire::get(out, true, 0x1234, 0x01020304, false);
  const uint8_t expected[] = {0x44,1,0x12,0x34,1,2,3,4,0xb6,'s','e','n','s','o','r'};
  assert(n == sizeof(expected) && memcmp(out, expected, n) == 0);
  wire::Message m;
  // ACK + token + Content-Format + Block2(0,M=1,SZX=6) + Size2 + payload.
  const uint8_t response[] = {0x64,69,0x12,0x34,1,2,3,4,0xc1,42,0xb1,14,0x52,0x80,0,255,'A','B'};
  assert(wire::parse(response, sizeof(response), m));
  assert(m.mid == 0x1234 && m.hasBlock && m.block == 14 && m.hasSize && m.size == 32768);
  assert(m.payloadLen == 2 && m.payload[1] == 'B');
  const uint8_t badToken[] = {0x49,1,0,0};
  assert(!wire::parse(badToken, sizeof(badToken), m));
  const uint8_t badOption[] = {0x60,69,0,0,0xdd,0};
  assert(!wire::parse(badOption, sizeof(badOption), m));
  const uint8_t marker[] = {0x60,69,0,0,255};
  assert(!wire::parse(marker, sizeof(marker), m));
  const uint8_t reservedBlock[] = {0x60,69,0,0,0xd1,10,7};
  assert(!wire::parse(reservedBlock, sizeof(reservedBlock), m));
  assert(wire::get(out, true, 1, 1, true, 0, 7) == 0);
  for (unsigned szx = 0; szx < 7; szx++) {
    n = wire::get(out, true, 0x1234, 0x01020304, true, 32768 / (1 << (szx + 4)) - 1, szx);
    assert(n > 8 && n <= sizeof(out));
  }
  puts("CoAP firmware wire tests passed");
}
