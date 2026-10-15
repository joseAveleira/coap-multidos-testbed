#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdarg>
#include <string>
#include <cstring>
#include <vector>
#include <deque>
#include <algorithm>
inline uint32_t testMillis = 0;
inline uint32_t millis() { return testMillis; }
inline uint32_t micros() { return testMillis * 1000u; }
inline void delay(uint32_t n) { testMillis += n; }
class IPAddress {
  uint8_t b[4] = {};
public:
  bool fromString(const char* str) {
    unsigned a, c, d, e;
    if (sscanf(str, "%u.%u.%u.%u", &a, &c, &d, &e) != 4 || a > 255 || c > 255 || d > 255 || e > 255) return false;
    b[0] = a; b[1] = c; b[2] = d; b[3] = e; return true;
  }
  uint8_t operator[](size_t i) const { return b[i]; }
  bool operator!=(const IPAddress& other) const { return memcmp(b, other.b, 4) != 0; }
  std::string toString() const { char s[32]; snprintf(s, sizeof(s), "%u.%u.%u.%u", b[0], b[1], b[2], b[3]); return s; }
};
struct FakeSerial {
  std::string output, input;
  void begin(unsigned) {}
  size_t setTxBufferSize(size_t n) { return n; }
  int availableForWrite() { return 1 << 20; }
  size_t write(const uint8_t* bytes, size_t n) { output.append(reinterpret_cast<const char*>(bytes), n); return n; }
  int available() { return input.size(); }
  char read() { char c = input.front(); input.erase(0, 1); return c; }
  void printf(const char* fmt, ...) {
    char b[2048]; va_list a; va_start(a, fmt); vsnprintf(b, sizeof(b), fmt, a); va_end(a); output += b;
  }
};
inline FakeSerial Serial;

