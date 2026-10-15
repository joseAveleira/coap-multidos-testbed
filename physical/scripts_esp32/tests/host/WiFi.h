#pragma once
#include "Arduino.h"
constexpr int WIFI_STA = 1, WL_CONNECTED = 3;
struct FakeWiFi {
  int state = WL_CONNECTED;
  void setHostname(const char*) {}
  void mode(int) {}
  void setSleep(bool) {}
  void setAutoReconnect(bool) {}
  void begin(const char*, const char*) {}
  void reconnect() {}
  int status() { return state; }
  int RSSI() { return -50; }
  IPAddress localIP() { IPAddress ip; ip.fromString("192.168.1.101"); return ip; }
};
inline FakeWiFi WiFi;

