// Native state-machine test with fake Arduino/Wi-Fi/clock, not a hardware build.
#include "client.h"
#include <cassert>
#include <iostream>

static std::vector<uint8_t> reply(const std::vector<uint8_t>& q) {
  bool large = q[9] == 'l';
  std::vector<uint8_t> r(q.begin(), q.begin() + 8);
  r[0] = (q[0] & 0x30) == 0 ? 0x64 : 0x54; r[1] = 69;
  if (!large) { r.insert(r.end(), {0xc0, 255, 't', '=', '2', '3'}); return r; }
  size_t at = 14; unsigned n = q[at++] & 15, block = 0;
  for (unsigned i = 0; i < n; i++) block = (block << 8) | q[at++];
  unsigned szx = block & 7, size = 1 << (szx + 4), offset = (block >> 4) * size;
  unsigned value = block | (offset + size < 32768 ? 8 : 0);
  r.insert(r.end(), {0x44, 1, 2, 3, 4, 0x81, 42}); // ETag and format.
  n = value > 255 ? 2 : value ? 1 : 0; r.push_back(0xb0 | n);
  for (unsigned i = 0; i < n; i++) r.push_back(value >> (8 * (n - i - 1)));
  r.insert(r.end(), {0x52, 0x80, 0, 255});
  for (unsigned i = 0; i < size; i++) r.push_back('A' + ((offset + i + 2026) % 26));
  return r;
}

int main() {
  Experiment client; client.setup();
  unsigned requests = 0, large = 0, non = 0;
  // Profile 5 polls with NON (no retransmission): skip the loss/retransmission check.
  const bool slowCon = !profileFor(PROFILE_ID).sensorNon;
  bool firstLost = !slowCon, retried = false;
  uint32_t lostAt = 0; std::vector<uint8_t> lostPacket;
  while (testMillis < 620000) {
    client.loop();
    while (!testTx.empty()) {
      auto q = testTx.front(); testTx.pop_front();
      if (q.bytes[1] == 0) continue;
      requests++; large += q.bytes[9] == 'l'; non += (q.bytes[0] & 0x30) == 0x10;
      if (!firstLost) { firstLost = true; lostPacket = q.bytes; lostAt = testMillis; continue; }
      if (slowCon && !retried) { assert(q.bytes == lostPacket); assert(testMillis - lostAt >= 2000); retried = true; }
      testRx.push_back({reply(q.bytes), q.ip, q.port});
    }
    testMillis++;
  }
  assert(requests > 50 && (retried || !slowCon));
  assert(Serial.output.find("\"event\":\"session_end\"") != std::string::npos);
  assert(Serial.output.find("response_error") == std::string::npos);
  assert(Serial.output.find("\"timeouts\":0") != std::string::npos);
  if (PROFILE_ID == 2) assert(non > 10);
  if (PROFILE_ID == 5) assert(non > 500);
  if (PROFILE_ID == 3) {
    assert(large >= 32);
    assert(Serial.output.find("download_verified") != std::string::npos);
  }
  if (PROFILE_ID == 4) assert(large >= 6);
  // Fast legitimate episodes: profiles 2-4 only, every episode fully answered.
  unsigned episodes = 0, fastRequests = 0, transfers = 0;
  for (size_t at = Serial.output.find("\"event\":\"fast_end\""); at != std::string::npos;
       at = Serial.output.find("\"event\":\"fast_end\"", at + 1)) {
    unsigned long ms, sentFast, receivedFast, timeoutsFast, errorsFast, sendFailedFast, skippedFast, cancelledFast, transfersFast;
    int fields = sscanf(Serial.output.c_str() + at - 1,
      "{\"event\":\"fast_end\",\"device\":%*d,\"ms\":%lu,\"sent\":%lu,\"received\":%lu,\"timeouts\":%lu,\"errors\":%lu,\"send_failed\":%lu,\"skipped\":%lu,\"cancelled\":%lu,\"transfers\":%lu}",
      &ms, &sentFast, &receivedFast, &timeoutsFast, &errorsFast, &sendFailedFast, &skippedFast, &cancelledFast, &transfersFast);
    assert(fields == 9);
    if (cancelledFast) continue; // The session end can cut the last episode.
    assert(sentFast > 30 && receivedFast == sentFast && !timeoutsFast && !errorsFast && !sendFailedFast);
    episodes++; fastRequests += sentFast; transfers += transfersFast;
  }
  assert((PROFILE_ID == 1) == (episodes == 0));
  if (PROFILE_ID > 1) assert(episodes >= 20);
  if (PROFILE_ID == 3) assert(transfers >= episodes);
  assert(Serial.output.find("\"mid_exhausted\":0") != std::string::npos);
  // Wi-Fi loss stops the session; it resumes on its own after reconnection...
  Serial.input = "START\n"; client.loop();
  WiFi.state = 0; client.loop(); assert(Serial.output.find("wifi_disconnected") != std::string::npos);
  WiFi.state = WL_CONNECTED; testTx.clear(); testRx.clear();
  for (unsigned i = 0; i < 10000; i++) { client.loop(); testMillis++; }
  assert(Serial.output.find("session_resume_scheduled") != std::string::npos);
  assert(!testTx.empty());
  // ...unless it was stopped manually.
  Serial.input = "STOP\n"; client.loop();
  WiFi.state = 0; client.loop(); WiFi.state = WL_CONNECTED; testTx.clear(); testRx.clear();
  for (unsigned i = 0; i < 10000; i++) { client.loop(); testMillis++; }
  assert(testTx.empty());
  std::cout << "Profile " << PROFILE_ID << ": " << requests << " requests; " << large
            << " Block2; " << non << " NON; " << episodes << " fast episodes (" << fastRequests
            << " requests); retransmission, resume and manual-stop checks passed\n";
}
