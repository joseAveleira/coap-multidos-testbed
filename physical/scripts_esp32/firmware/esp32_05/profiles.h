#pragma once
#include <stdint.h>

// Episodios rápidos legítimos, inspirados en los clientes .10, .11 y .12 del
// simulador original: duran 2-5 s y se repiten cada 8-20 s (~20 % del tiempo).
// Tasas reducidas respecto al simulador (650/500 pet/s) a lo que sostiene la red
// física: por encima de ~300 pet/s por placa fallan los envíos y suben los
// timeouts (calibración del 14-10-2026). Varias peticiones en vuelo, ritmo fijo,
// sin retransmisión, como el actor.
// FAST_MIXED elige en cada episodio uno de los tres tipos, como el cliente .10.
enum FastKind : uint8_t {FAST_NONE, FAST_SENSOR, FAST_DOWNLOAD, FAST_READS, FAST_MIXED};
constexpr uint16_t FAST_SENSOR_RPS[] = {40, 80, 150, 250};
constexpr uint16_t FAST_BLOCK_RPS[] = {20, 50, 100, 200};
constexpr unsigned FAST_RATE_CHOICES = sizeof(FAST_SENSOR_RPS) / sizeof(FAST_SENSOR_RPS[0]);
static_assert(sizeof(FAST_BLOCK_RPS) == sizeof(FAST_SENSOR_RPS), "Mismo número de tasas");

struct Profile {
  const char* name;
  uint32_t sensorMs, sensorJitterMs;
  uint32_t burstEveryMs, burstJitterMs, burstDurationMs, burstIntervalMs;
  uint32_t downloadEveryMs, downloadJitterMs, blockGapMs;
  uint32_t cacheEveryMs, cacheJitterMs;
  FastKind fastKind;
  uint32_t fastMinMs, fastMaxMs, fastGapMinMs, fastGapMaxMs;
  bool sensorNon; // Lecturas periódicas NON (telemetría) en lugar de CON.
};
// Identidad física y perfil separados: PROFILE_ID puede rotarse entre placas.
inline Profile profileFor(unsigned id) {
  switch (id) {
    case 1: return {"control_periodico", 750, 250, 0, 0, 0, 0, 0, 0, 20, 0, 0,
                    FAST_NONE, 0, 0, 0, 0, false};
    case 2: return {"lectura_eventos", 2000, 600, 30000, 10000, 3000, 100, 0, 0, 20, 0, 0,
                    FAST_SENSOR, 2000, 5000, 8000, 20000, false};
    case 3: return {"sincronizacion_config", 2500, 500, 0, 0, 0, 0, 60000, 15000, 20, 0, 0,
                    FAST_DOWNLOAD, 2000, 5000, 8000, 20000, false};
    case 4: return {"supervision_cache", 1000, 200, 0, 0, 0, 0, 0, 0, 100, 20000, 5000,
                    FAST_READS, 2000, 5000, 8000, 20000, false};
    // Pasarela: reenvía telemetría NON y sincroniza contenido para otros nodos.
    case 5: return {"pasarela_mixta", 500, 200, 0, 0, 0, 0, 0, 0, 20, 0, 0,
                    FAST_MIXED, 2000, 5000, 8000, 20000, true};
    default: return profileFor(1); // Inalcanzable: PROFILE_ID se valida en client.h.
  }
}
inline const char* fastKindName(FastKind kind) {
  switch (kind) { case FAST_SENSOR: return "sensor"; case FAST_DOWNLOAD: return "block2_download";
    case FAST_READS: return "block2_reads"; case FAST_MIXED: return "mixed"; default: return "none"; }
}
