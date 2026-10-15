#pragma once
#include <Arduino.h>
#include <WiFi.h>
#include <esp_system.h>
#include "config.h"
#include "profiles.h"
#include "coap_wire.h"
#include "link.h"

#ifndef DEVICE_ID
#define DEVICE_ID 1
#endif
#ifndef PROFILE_ID
#define PROFILE_ID DEVICE_ID
#endif
static_assert(DEVICE_ID >= 1 && DEVICE_ID <= 5, "DEVICE_ID debe ser 1..5");
static_assert(PROFILE_ID >= 1 && PROFILE_ID <= 4, "PROFILE_ID debe ser 1..4");
static_assert(lab::BLOCK_SZX <= 6, "Block2 SZX debe ser 0..6");
static_assert(lab::SESSION_MS < 0x7fffffffUL, "Duracion no valida");

class Experiment {
  enum Job {SENSOR, BURST, DOWNLOAD, CACHE};
  struct InFlight { bool used; bool con; uint16_t mid; uint32_t token, sentAt, block; };
  static constexpr size_t FAST_SLOTS = 128;
  static constexpr uint32_t BLOCKS = lab::RESOURCE_BYTES >> (lab::BLOCK_SZX + 4);
  static constexpr uint32_t MID_WINDOW_S = 248; // > EXCHANGE_LIFETIME (247 s).
  Link link;
  IPAddress server;
  Profile profile = profileFor(PROFILE_ID);
  bool configured = false, connected = false, active = false, autoPending = lab::AUTO_START;
  bool resumePending = false;
  uint32_t randomState = 1, midCounter = 0, tokenCounter = 0;
  // Fast episodes use their own generator so the slow schedule stays unchanged.
  uint32_t fastRandomState = 1;
  InFlight inflight[FAST_SLOTS] = {};
  bool fastActive = false, fastCon = false, fastReportPending = false;
  uint32_t nextFast = 0, fastEnd = 0, fastReportAt = 0, fastRate = 0, fastIntervalUs = 0, fastDueUs = 0;
  uint32_t fastToken = 0, fastBlock = 0, fastFixedBlock = 0;
  uint32_t fSent = 0, fReceived = 0, fTimeouts = 0, fErrors = 0, fSendFailed = 0, fSkipped = 0, fTransfers = 0;
  uint32_t fastEpisodes = 0, fastSent = 0, fastReceived = 0, fastTimeouts = 0, fastErrors = 0, fastSendFailed = 0, fastSkipped = 0;
  // A MID is reused only after more than 65000 allocations in the last 248 s.
  uint16_t midCount[MID_WINDOW_S] = {};
  uint32_t midSum = 0, midLastSecond = 0, midExhausted = 0;
  uint32_t connectAttempt = 0, autoAt = 0, startAt = 0, nextSensor = 0;
  uint32_t nextBurst = 0, burstEnd = 0, nextBurstRequest = 0;
  uint32_t nextDownload = 0, nextCache = 0, nextBlock = 0, nextSummary = 0;
  bool bursting = false, downloading = false;
  uint32_t blockNumber = 0, transferToken = 0, transferBytes = 0;
  uint32_t cacheBlock = 0; uint8_t cacheRemaining = 0;
  uint8_t transferEtag[8] = {}, transferEtagLen = 0;
  uint8_t firstResourceByte = 0;
  uint16_t lastSeparateMid = 0; uint32_t lastSeparateAt = 0;
  bool haveSeparate = false;
  struct Pending {
    bool used = false, con = false, acknowledged = false;
    Job job = SENSOR;
    uint16_t mid = 0;
    uint32_t token = 0, sentAt = 0, deadline = 0, waitMs = 0, block = 0;
    uint8_t retries = 0, packet[32] = {};
    size_t length = 0;
  } pending;
  uint32_t sent = 0, received = 0, timeouts = 0, retransmits = 0, failures = 0, downloads = 0;
  char command[40] = {}; size_t commandLen = 0;

  static bool due(uint32_t now, uint32_t deadline) { return int32_t(now - deadline) >= 0; }
  static uint32_t xorshift(uint32_t& state) {
    uint32_t x = state; x ^= x << 13; x ^= x >> 17; x ^= x << 5; return state = x;
  }
  uint32_t random() { return xorshift(randomState); }
  uint32_t interval(uint32_t base, uint32_t jitter) { return base + (jitter ? random() % (jitter + 1) : 0); }
  uint32_t fastBetween(uint32_t low, uint32_t high) {
    return low + (high > low ? xorshift(fastRandomState) % (high - low + 1) : 0);
  }
  bool takeMid(uint32_t now, uint16_t& mid) {
    const uint32_t second = now / 1000;
    uint32_t steps = second - midLastSecond;
    if (steps > MID_WINDOW_S) steps = MID_WINDOW_S;
    for (uint32_t k = 1; k <= steps; k++) {
      const uint32_t i = (midLastSecond + k) % MID_WINDOW_S; midSum -= midCount[i]; midCount[i] = 0;
    }
    midLastSecond = second;
    if (midSum >= 65000) { midExhausted++; return false; }
    midCount[second % MID_WINDOW_S]++; midSum++; mid = uint16_t(++midCounter);
    return true;
  }
  uint32_t nextToken() { if (!++tokenCounter) ++tokenCounter; return tokenCounter; }
  const char* jobName(Job job) {
    switch (job) { case SENSOR: return "sensor"; case BURST: return "sensor_burst";
      case DOWNLOAD: return "block2_download"; default: return "block2_cache"; }
  }
  void event(const char* name) {
    Serial.printf("{\"event\":\"%s\",\"device\":%d,\"profile\":%d,\"ms\":%lu}\n", name, DEVICE_ID, PROFILE_ID, (unsigned long)millis());
  }
  bool transmit(const uint8_t* bytes, size_t length) { return link.send(bytes, length); }
  void summary() {
    Serial.printf("{\"event\":\"summary\",\"device\":%d,\"ms\":%lu,\"sent\":%lu,\"received\":%lu,\"timeouts\":%lu,\"retransmits\":%lu,\"failures\":%lu,\"downloads\":%lu,\"fast_episodes\":%lu,\"fast_sent\":%lu,\"fast_received\":%lu,\"fast_timeouts\":%lu,\"fast_errors\":%lu,\"fast_send_failed\":%lu,\"fast_skipped\":%lu,\"mid_exhausted\":%lu,\"rx_overflow\":%lu,\"rssi\":%d}\n",
      DEVICE_ID, (unsigned long)millis(), (unsigned long)sent, (unsigned long)received,
      (unsigned long)timeouts, (unsigned long)retransmits, (unsigned long)failures,
      (unsigned long)downloads, (unsigned long)fastEpisodes, (unsigned long)fastSent,
      (unsigned long)fastReceived, (unsigned long)fastTimeouts, (unsigned long)fastErrors,
      (unsigned long)fastSendFailed, (unsigned long)fastSkipped, (unsigned long)midExhausted, (unsigned long)link.overflows(), WiFi.RSSI());
  }
  void stop(const char* reason) {
    if (!active) return;
    if (pending.used) event("request_cancelled");
    if (downloading) event("download_cancelled");
    if (fastActive || fastReportPending) {
      uint32_t cancelled = 0;
      for (auto& f : inflight) if (f.used) { f.used = false; cancelled++; }
      fastActive = false; reportFast(cancelled);
    }
    active = false; pending.used = false; downloading = false; bursting = false; cacheRemaining = 0;
    event(reason); summary();
  }
  void beginFast(uint32_t now) {
    const bool sensor = profile.fastKind == FAST_SENSOR;
    fastRate = (sensor ? FAST_SENSOR_RPS : FAST_BLOCK_RPS)[xorshift(fastRandomState) % FAST_RATE_CHOICES];
    fastCon = profile.fastKind == FAST_DOWNLOAD || (xorshift(fastRandomState) & 1);
    fastFixedBlock = xorshift(fastRandomState) % BLOCKS; fastBlock = BLOCKS; // New transfer on first send.
    fastIntervalUs = 1000000UL / fastRate; fastDueUs = micros();
    const uint32_t duration = fastBetween(profile.fastMinMs, profile.fastMaxMs);
    fastEnd = now + duration;
    fSent = fReceived = fTimeouts = fErrors = fSendFailed = fSkipped = fTransfers = 0;
    fastActive = true; fastEpisodes++;
    Serial.printf("{\"event\":\"fast_start\",\"device\":%d,\"ms\":%lu,\"kind\":\"%s\",\"rate_rps\":%lu,\"type\":\"%s\",\"duration_ms\":%lu,\"block\":%ld}\n",
      DEVICE_ID, (unsigned long)now, fastKindName(profile.fastKind), (unsigned long)fastRate,
      fastCon ? "CON" : "NON", (unsigned long)duration,
      profile.fastKind == FAST_READS ? long(fastFixedBlock) : -1L);
  }
  void reportFast(uint32_t cancelled = 0) {
    fastReportPending = false;
    fastSent += fSent; fastReceived += fReceived; fastTimeouts += fTimeouts;
    fastErrors += fErrors; fastSendFailed += fSendFailed; fastSkipped += fSkipped;
    Serial.printf("{\"event\":\"fast_end\",\"device\":%d,\"ms\":%lu,\"sent\":%lu,\"received\":%lu,\"timeouts\":%lu,\"errors\":%lu,\"send_failed\":%lu,\"skipped\":%lu,\"cancelled\":%lu,\"transfers\":%lu}\n",
      DEVICE_ID, (unsigned long)millis(), (unsigned long)fSent, (unsigned long)fReceived,
      (unsigned long)fTimeouts, (unsigned long)fErrors, (unsigned long)fSendFailed, (unsigned long)fSkipped,
      (unsigned long)cancelled, (unsigned long)fTransfers);
  }
  void sendFast(uint32_t now) {
    size_t slot = FAST_SLOTS;
    for (size_t i = 0; i < FAST_SLOTS; i++) if (!inflight[i].used) { slot = i; break; }
    if (slot == FAST_SLOTS) { fSkipped++; return; }
    uint32_t block = fastFixedBlock, token;
    if (profile.fastKind == FAST_DOWNLOAD) {
      if (fastBlock >= BLOCKS) { fastToken = nextToken(); fastBlock = 0; fTransfers++; }
      block = fastBlock; token = fastToken;
    } else token = nextToken();
    uint16_t mid;
    if (!takeMid(now, mid)) { fSkipped++; return; }
    uint8_t packet[32];
    const size_t length = wire::get(packet, fastCon, mid, token, profile.fastKind != FAST_SENSOR, block, lab::BLOCK_SZX);
    if (!length || !transmit(packet, length)) { fSendFailed++; return; } // Wi-Fi TX queue full.
    if (profile.fastKind == FAST_DOWNLOAD) fastBlock++;
    inflight[slot] = {true, fastCon, mid, token, now, block};
    fSent++;
  }
  bool fastResponse(const wire::Message& m) {
    if (m.type == 3 && m.code == 0) {
      for (auto& f : inflight) if (f.used && f.con && f.mid == m.mid) { f.used = false; fErrors++; return true; }
      return false;
    }
    if (m.code < 64 || m.tokenLen != 4) return false;
    const uint32_t token = (uint32_t(m.token[0]) << 24) | (uint32_t(m.token[1]) << 16) |
                           (uint32_t(m.token[2]) << 8) | m.token[3];
    for (auto& f : inflight) {
      if (!f.used || f.token != token) continue;
      // CON: piggybacked ACK with the same MID. NON: NON response with a new MID.
      if (m.type == 2 ? !(f.con && f.mid == m.mid) : !(m.type == 1 && !f.con)) continue;
      bool ok = m.code == 69;
      if (ok && profile.fastKind != FAST_SENSOR)
        ok = m.hasBlock && (m.block >> 4) == f.block && (m.block & 7) == lab::BLOCK_SZX &&
             m.payloadLen == (1UL << (lab::BLOCK_SZX + 4)) && m.etagLen;
      if (ok) fReceived++; else fErrors++;
      f.used = false;
      return true;
    }
    return false;
  }
  void fastTick(uint32_t now) {
    if (profile.fastKind == FAST_NONE) return;
    bool inFlight = false;
    for (auto& f : inflight) {
      if (f.used && now - f.sentAt >= lab::FAST_TIMEOUT_MS) { f.used = false; fTimeouts++; }
      inFlight |= f.used;
    }
    if (fastReportPending && (!inFlight || due(now, fastReportAt))) reportFast();
    if (!fastActive) {
      if (fastReportPending || !due(now, nextFast)) return;
      beginFast(now);
    }
    if (due(now, fastEnd)) {
      fastActive = false; fastReportPending = true; fastReportAt = now + lab::FAST_TIMEOUT_MS;
      nextFast = now + fastBetween(profile.fastGapMinMs, profile.fastGapMaxMs);
      return;
    }
    // Fixed-rate pacing: catch up a few slots per loop, then count the rest as skipped.
    const uint32_t us = micros();
    for (int k = 0; k < 8 && int32_t(us - fastDueUs) >= 0; k++) { sendFast(now); fastDueUs += fastIntervalUs; }
    if (int32_t(us - fastDueUs) >= 0) {
      const uint32_t behind = (us - fastDueUs) / fastIntervalUs + 1;
      fSkipped += behind; fastDueUs += behind * fastIntervalUs;
    }
  }
  void start() {
    if (!connected) { event("start_requires_wifi"); return; }
    if (active) stop("session_restarted");
    randomState = lab::SESSION_SEED ^ (uint32_t(0x9e3779b9U) * uint32_t(DEVICE_ID)); if (!randomState) randomState = 1;
    fastRandomState = randomState ^ 0x85ebca6bU; if (!fastRandomState) fastRandomState = 1;
    active = true; autoPending = false; startAt = millis();
    sent = received = timeouts = retransmits = failures = downloads = 0;
    fastEpisodes = fastSent = fastReceived = fastTimeouts = fastErrors = fastSendFailed = fastSkipped = 0;
    fastActive = fastReportPending = false;
    for (auto& f : inflight) f.used = false;
    nextSensor = startAt + interval(100, 1000);
    nextBurst = startAt + interval(profile.burstEveryMs, profile.burstJitterMs);
    nextDownload = startAt + interval(5000, 5000);
    nextCache = startAt + interval(profile.cacheEveryMs, profile.cacheJitterMs);
    nextFast = startAt + fastBetween(profile.fastGapMinMs, profile.fastGapMaxMs);
    nextSummary = startAt + 5000;
    Serial.printf("{\"event\":\"session_start\",\"device\":%d,\"profile\":%d,\"name\":\"%s\",\"seed\":%lu,\"duration_ms\":%lu,\"ms\":%lu,\"ip\":\"%s\",\"server\":\"%s\",\"port\":%u,\"szx\":%u,\"wifi_sleep\":%s,\"resume_after_wifi\":%s,\"sensor_ms\":%lu,\"burst_interval_ms\":%lu,\"download_every_ms\":%lu,\"fast_kind\":\"%s\",\"fast_ms\":[%lu,%lu],\"fast_gap_ms\":[%lu,%lu]}\n",
      DEVICE_ID, PROFILE_ID, profile.name, (unsigned long)lab::SESSION_SEED,
      (unsigned long)lab::SESSION_MS, (unsigned long)startAt, WiFi.localIP().toString().c_str(),
      server.toString().c_str(), lab::SERVER_PORT, lab::BLOCK_SZX, lab::WIFI_SLEEP ? "true" : "false",
      lab::RESUME_AFTER_WIFI ? "true" : "false",
      (unsigned long)profile.sensorMs, (unsigned long)profile.burstIntervalMs, (unsigned long)profile.downloadEveryMs,
      fastKindName(profile.fastKind), (unsigned long)profile.fastMinMs, (unsigned long)profile.fastMaxMs,
      (unsigned long)profile.fastGapMinMs, (unsigned long)profile.fastGapMaxMs);
  }
  void abortJob() {
    if (pending.job == DOWNLOAD) { downloading = false; event("download_aborted"); }
    if (pending.job == CACHE) cacheRemaining = 0;
    pending.used = false;
  }
  void request(Job job, bool con, uint32_t block = 0, uint32_t token = 0) {
    uint16_t mid;
    if (!takeMid(millis(), mid)) { failures++; event("mid_exhausted"); return; }
    pending = Pending{}; pending.used = true; pending.job = job; pending.con = con;
    pending.mid = mid; pending.token = token ? token : nextToken();
    pending.block = block;
    pending.length = wire::get(pending.packet, con, pending.mid, pending.token, job >= DOWNLOAD, block, lab::BLOCK_SZX);
    pending.sentAt = millis(); pending.waitMs = con ? interval(2000, 1000) : lab::NON_TIMEOUT_MS;
    pending.deadline = pending.sentAt + pending.waitMs;
    if (!pending.length || !transmit(pending.packet, pending.length)) { failures++; event("send_error"); abortJob(); return; }
    sent++;
  }
  bool blockValid(const wire::Message& m) {
    const uint32_t size = 1UL << (lab::BLOCK_SZX + 4), offset = pending.block * size;
    if (!m.hasBlock || (m.block >> 4) != pending.block || (m.block & 7) != lab::BLOCK_SZX ||
        !m.hasSize || m.size != lab::RESOURCE_BYTES || offset >= lab::RESOURCE_BYTES ||
        m.payloadLen != size || bool(m.block & 8) != (offset + size < lab::RESOURCE_BYTES) || !m.etagLen) return false;
    if (pending.job == DOWNLOAD) {
      if (!pending.block) {
        transferEtagLen = m.etagLen; memcpy(transferEtag, m.etag, m.etagLen);
        firstResourceByte = m.payload[0]; if (firstResourceByte < 'A' || firstResourceByte > 'Z') return false;
      } else if (m.etagLen != transferEtagLen || memcmp(m.etag, transferEtag, transferEtagLen)) return false;
      // Verify every byte without storing the 32-KiB representation in RAM.
      for (size_t i = 0; i < m.payloadLen; i++)
        if (m.payload[i] != uint8_t('A' + ((firstResourceByte - 'A' + offset + i) % 26))) return false;
    }
    return true;
  }
  void receive() {
    // Bounded loop keeps USB commands and deadlines responsive under traffic.
    // Link has already discarded datagrams from other peers.
    for (int k = 0; k < 32; k++) {
      uint8_t bytes[1200];
      const int n = link.poll(bytes, sizeof(bytes)); if (!n) return;
      wire::Message m; if (!wire::parse(bytes, size_t(n), m)) continue;
      if (fastResponse(m)) continue;
      if (m.type == 0 && haveSeparate && m.mid == lastSeparateMid && millis() - lastSeparateAt < 247000) {
        uint8_t ack[4]; wire::ack(ack, m.mid); transmit(ack, 4); continue;
      }
      if (!pending.used) continue;
      if (m.type == 3 && m.code == 0 && m.mid == pending.mid) { failures++; event("reset"); abortJob(); continue; }
      if (m.type == 2 && m.code == 0 && m.mid == pending.mid && pending.con) {
        if (!pending.acknowledged) { pending.acknowledged = true; pending.deadline = millis() + lab::SEPARATE_RESPONSE_MS; }
        continue;
      }
      if (m.tokenLen != 4 || memcmp(m.token, pending.packet + 4, 4) || m.code < 64 || m.type == 3) continue;
      if (m.type == 2 && (!pending.con || m.mid != pending.mid)) continue;
      if (m.type == 0) {
        uint8_t ack[4]; wire::ack(ack, m.mid); transmit(ack, 4);
        lastSeparateMid = m.mid; lastSeparateAt = millis(); haveSeparate = true;
      }
      if (m.code != 69 || (pending.job >= DOWNLOAD && !blockValid(m))) {
        failures++; event("response_error"); abortJob(); continue;
      }
      received++;
      Serial.printf("{\"event\":\"response\",\"device\":%d,\"ms\":%lu,\"job\":\"%s\",\"mid\":%u,\"token\":\"%08lx\",\"elapsed_ms\":%lu,\"retries\":%u,\"payload_bytes\":%u,\"block\":%lu}\n",
        DEVICE_ID, (unsigned long)millis(), jobName(pending.job), pending.mid,
        (unsigned long)pending.token, (unsigned long)(millis() - pending.sentAt), pending.retries,
        unsigned(m.payloadLen), (unsigned long)pending.block);
      if (pending.job == DOWNLOAD) {
        transferBytes += m.payloadLen; blockNumber++;
        if (!(m.block & 8)) { downloading = false; downloads++; event("download_verified"); }
        nextBlock = millis() + profile.blockGapMs;
      } else if (pending.job == CACHE) { cacheRemaining--; nextBlock = millis() + profile.blockGapMs; }
      pending.used = false;
    }
  }
  void handleTimeout(uint32_t now) {
    if (!pending.used || !due(now, pending.deadline)) return;
    if (pending.con && !pending.acknowledged && pending.retries < lab::MAX_RETRANSMIT) {
      if (!transmit(pending.packet, pending.length)) { failures++; event("send_error"); abortJob(); return; }
      pending.retries++; retransmits++; pending.waitMs *= 2; pending.deadline = now + pending.waitMs;
    } else {
      timeouts++;
      Serial.printf("{\"event\":\"timeout\",\"device\":%d,\"ms\":%lu,\"job\":\"%s\",\"mid\":%u,\"elapsed_ms\":%lu,\"retries\":%u}\n",
        DEVICE_ID, (unsigned long)now, jobName(pending.job), pending.mid,
        (unsigned long)(now - pending.sentAt), pending.retries);
      abortJob();
    }
  }
  void serialCommands() {
    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\r') continue;
      if (c == '\n') {
        command[commandLen] = 0;
        if (!strcmp(command, "START")) start();
        else if (!strcmp(command, "STOP")) { autoPending = resumePending = false; stop("manual_stop"); }
        else if (!strcmp(command, "STATUS")) summary();
        else event("commands_START_STOP_STATUS");
        commandLen = 0;
      } else if (commandLen < sizeof(command) - 1) command[commandLen++] = c;
    }
  }
public:
  void setup() {
    Serial.begin(115200); // No espera infinita a que el PC abra USB.
    midCounter = esp_random() & 65535; tokenCounter = esp_random();
    configured = strcmp(LAB_WIFI_SSID, "CAMBIAR_WIFI") && server.fromString(LAB_SERVER_IP) && server[0] != 0;
    if (!configured) { event("edit_config_wifi_and_server"); return; }
    char host[24]; snprintf(host, sizeof(host), "coap-esp32-%02d", DEVICE_ID);
    WiFi.setHostname(host); WiFi.mode(WIFI_STA); WiFi.setSleep(lab::WIFI_SLEEP);
    WiFi.setAutoReconnect(true); WiFi.begin(LAB_WIFI_SSID, LAB_WIFI_PASSWORD);
    connectAttempt = millis();
  }
  void loop() {
    serialCommands();
    if (!configured) { delay(20); return; }
    uint32_t now = millis();
    if (WiFi.status() != WL_CONNECTED) {
      if (connected) {
        resumePending = active && lab::RESUME_AFTER_WIFI;
        stop("wifi_disconnected"); link.stop(); connected = false;
      }
      if (now - connectAttempt >= 15000) { WiFi.reconnect(); connectAttempt = now; event("wifi_retry"); }
      delay(5); return;
    }
    if (!connected) {
      if (!link.begin(server, lab::SERVER_PORT, 56830 + DEVICE_ID)) { event("udp_bind_failed"); delay(1000); return; }
      connected = true; autoAt = now + lab::START_DELAY_MS;
      Serial.printf("{\"event\":\"ready\",\"device\":%d,\"ip\":\"%s\",\"local_port\":%u}\n", DEVICE_ID,
        WiFi.localIP().toString().c_str(), 56830 + DEVICE_ID);
      if (resumePending) { resumePending = false; autoPending = true; event("session_resume_scheduled"); }
    }
    if (autoPending && due(now, autoAt)) start();
    receive(); handleTimeout(now);
    if (!active) { delay(1); return; }
    if (lab::SESSION_MS && now - startAt >= lab::SESSION_MS) { stop("session_end"); return; }
    if (due(now, nextSummary)) { summary(); nextSummary = now + 5000; }
    fastTick(now);
    if (pending.used) { delay(1); return; } // Slow lane: one outstanding request (NSTART=1).
    if (bursting && due(now, burstEnd)) { bursting = false; event("burst_end"); }
    if (profile.burstEveryMs && !bursting && due(now, nextBurst)) {
      bursting = true; burstEnd = now + profile.burstDurationMs; nextBurstRequest = now;
      nextBurst = now + interval(profile.burstEveryMs, profile.burstJitterMs); event("burst_start");
    }
    if (profile.downloadEveryMs && !downloading && due(now, nextDownload)) {
      downloading = true; blockNumber = 0; transferBytes = 0; transferEtagLen = 0;
      transferToken = ++tokenCounter; if (!transferToken) transferToken = ++tokenCounter;
      nextBlock = now; nextDownload = now + interval(profile.downloadEveryMs, profile.downloadJitterMs);
      event("download_start");
    }
    if (profile.cacheEveryMs && !cacheRemaining && due(now, nextCache)) {
      cacheRemaining = 6; cacheBlock = random() % (lab::RESOURCE_BYTES / (1UL << (lab::BLOCK_SZX + 4)));
      nextBlock = now; nextCache = now + interval(profile.cacheEveryMs, profile.cacheJitterMs); event("cache_reads_start");
    }
    if (downloading && due(now, nextBlock)) request(DOWNLOAD, true, blockNumber, transferToken);
    else if (cacheRemaining && due(now, nextBlock)) request(CACHE, true, cacheBlock);
    else if (bursting && due(now, nextBurstRequest)) {
      request(BURST, false); nextBurstRequest = now + profile.burstIntervalMs;
    } else if (due(now, nextSensor)) {
      request(SENSOR, true); nextSensor = now + interval(profile.sensorMs, profile.sensorJitterMs);
    }
    delay(1);
  }
};
