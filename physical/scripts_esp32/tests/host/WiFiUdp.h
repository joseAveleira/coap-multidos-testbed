#pragma once
#include "Arduino.h"
struct FakeDatagram { std::vector<uint8_t> bytes; IPAddress ip; uint16_t port; };
inline std::deque<FakeDatagram> testRx, testTx;
class WiFiUDP {
  FakeDatagram incoming, outgoing;
  size_t readAt = 0;
public:
  int begin(uint16_t) { return 1; }
  void stop() { testRx.clear(); }
  int beginPacket(IPAddress ip, uint16_t port) { outgoing = {{}, ip, port}; return 1; }
  size_t write(const uint8_t* data, size_t n) { outgoing.bytes.insert(outgoing.bytes.end(), data, data + n); return n; }
  int endPacket() { testTx.push_back(outgoing); return 1; }
  int parsePacket() {
    if (testRx.empty()) return 0;
    incoming = testRx.front(); testRx.pop_front(); readAt = 0; return incoming.bytes.size();
  }
  int available() { return incoming.bytes.size() - readAt; }
  int read() { return available() ? incoming.bytes[readAt++] : -1; }
  int read(uint8_t* out, size_t n) {
    n = std::min(n, incoming.bytes.size() - readAt);
    memcpy(out, incoming.bytes.data() + readAt, n); readAt += n; return n;
  }
  IPAddress remoteIP() { return incoming.ip; }
  uint16_t remotePort() { return incoming.port; }
};

