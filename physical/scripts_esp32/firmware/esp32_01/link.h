#pragma once
// UDP endpoint of the client. On the ESP32 a dedicated task blocks on the socket
// and copies every datagram into a 64-entry ring as soon as it arrives: lwIP keeps
// only CONFIG_LWIP_UDP_RECVMBOX_SIZE (6) datagrams per socket and Wi-Fi delivers
// aggregated bursts, so polling from loop() lost ~25 % of responses at 200 req/s.
#include <Arduino.h>

#if defined(ARDUINO_ARCH_ESP32)
#include <atomic>
#include <lwip/sockets.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

class Link {
  static constexpr size_t SLOTS = 64, BYTES = 1200;
  struct Slot { uint16_t length; uint8_t data[BYTES]; };
  Slot ring[SLOTS];
  uint8_t scratch[BYTES];
  std::atomic<uint32_t> head{0}, tail{0};  // One producer (task), one consumer (loop).
  std::atomic<uint32_t> overflow{0}, oversize{0};
  int fd = -1;
  sockaddr_in to = {};

  static void receiver(void* arg) {
    Link& self = *static_cast<Link*>(arg);
    for (;;) {
      const uint32_t h = self.head.load(std::memory_order_relaxed);
      const bool full = h - self.tail.load(std::memory_order_acquire) >= SLOTS;
      uint8_t* target = full ? self.scratch : self.ring[h % SLOTS].data;
      sockaddr_in from = {}; socklen_t fromLength = sizeof(from);
      const int n = recvfrom(self.fd, target, BYTES, 0, reinterpret_cast<sockaddr*>(&from), &fromLength);
      if (n <= 0) { vTaskDelay(1); continue; }
      if (from.sin_addr.s_addr != self.to.sin_addr.s_addr || from.sin_port != self.to.sin_port) continue;
      if (size_t(n) >= BYTES) { self.oversize++; continue; }  // Possibly truncated.
      if (full) { self.overflow++; continue; }
      self.ring[h % SLOTS].length = uint16_t(n);
      self.head.store(h + 1, std::memory_order_release);
    }
  }

public:
  // The socket is bound once to INADDR_ANY and survives Wi-Fi reconnections.
  bool begin(IPAddress server, uint16_t serverPort, uint16_t localPort) {
    to.sin_family = AF_INET; to.sin_port = htons(serverPort);
    to.sin_addr.s_addr = uint32_t(server[0]) | (uint32_t(server[1]) << 8) |
                         (uint32_t(server[2]) << 16) | (uint32_t(server[3]) << 24);
    if (fd < 0) {
      const int socketFd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
      if (socketFd < 0) return false;
      sockaddr_in local = {}; local.sin_family = AF_INET; local.sin_port = htons(localPort);
      local.sin_addr.s_addr = htonl(INADDR_ANY);
      if (bind(socketFd, reinterpret_cast<sockaddr*>(&local), sizeof(local)) < 0) { close(socketFd); return false; }
      fd = socketFd;
      // Above loop() (priority 1) so draining never waits for the main loop.
      if (xTaskCreate(receiver, "coap_rx", 4096, this, 5, nullptr) != pdPASS) return false;
    }
    stop();
    return true;
  }
  bool send(const uint8_t* bytes, size_t length) {
    return fd >= 0 && sendto(fd, bytes, length, 0, reinterpret_cast<const sockaddr*>(&to), sizeof(to)) == int(length);
  }
  int poll(uint8_t* out, size_t capacity) {
    const uint32_t t = tail.load(std::memory_order_relaxed);
    if (t == head.load(std::memory_order_acquire)) return 0;
    const Slot& slot = ring[t % SLOTS];
    const int n = slot.length <= capacity ? slot.length : 0;
    memcpy(out, slot.data, n);
    tail.store(t + 1, std::memory_order_release);
    return n;
  }
  void stop() { tail.store(head.load(std::memory_order_acquire), std::memory_order_release); }
  uint32_t overflows() const { return overflow.load() + oversize.load(); }
};

#else
// Host tests: same interface over the fake WiFiUDP.
#include <WiFiUdp.h>

class Link {
  WiFiUDP udp;
  IPAddress server;
  uint16_t serverPort = 0;
public:
  bool begin(IPAddress address, uint16_t port, uint16_t localPort) {
    server = address; serverPort = port; return udp.begin(localPort);
  }
  bool send(const uint8_t* bytes, size_t length) {
    if (!udp.beginPacket(server, serverPort)) return false;
    if (udp.write(bytes, length) != length) { udp.endPacket(); return false; }
    return udp.endPacket() == 1;
  }
  int poll(uint8_t* out, size_t capacity) {
    for (;;) {
      const int length = udp.parsePacket(); if (!length) return 0;
      if (length > int(capacity)) { while (udp.available()) udp.read(); continue; }
      const int n = udp.read(out, capacity);
      if (n == length && !(udp.remoteIP() != server) && udp.remotePort() == serverPort) return n;
    }
  }
  void stop() { udp.stop(); }
  uint32_t overflows() const { return 0; }
};
#endif
