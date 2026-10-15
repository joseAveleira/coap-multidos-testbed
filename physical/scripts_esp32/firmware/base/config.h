#pragma once
#include <stdint.h>

// Opcional: crear config_local.h con estas tres macros; no se versiona.
#if __has_include("config_local.h")
#include "config_local.h"
#endif
#ifndef LAB_WIFI_SSID
#define LAB_WIFI_SSID "CAMBIAR_WIFI"
#endif
#ifndef LAB_WIFI_PASSWORD
#define LAB_WIFI_PASSWORD "CAMBIAR_CLAVE"
#endif
#ifndef LAB_SERVER_IP
#define LAB_SERVER_IP "192.168.1.100"
#endif

#ifndef LAB_SESSION_MS
#define LAB_SESSION_MS 0
#endif

namespace lab {
constexpr uint16_t SERVER_PORT = 5683;
constexpr uint32_t SESSION_SEED = 2026;
// 0 = sin límite: la placa funciona alimentada sin USB hasta que se apaga.
// Un valor > 0 (p. ej. -DLAB_SESSION_MS=600000) limita la sesión.
constexpr uint32_t SESSION_MS = LAB_SESSION_MS;
constexpr bool AUTO_START = true;
// Tras perder y recuperar la Wi-Fi, la sesión se reanuda salvo STOP manual.
constexpr bool RESUME_AFTER_WIFI = true;
constexpr uint32_t FAST_TIMEOUT_MS = 3000; // Igual que el actor; sin retransmisión.
constexpr uint32_t START_DELAY_MS = 5000;
constexpr bool WIFI_SLEEP = false; // Mantener y documentar el mismo ajuste.
constexpr uint8_t BLOCK_SZX = 6; // 1024 bytes; admite 0..6 (16..1024).
constexpr uint32_t RESOURCE_BYTES = 32768;
constexpr uint32_t NON_TIMEOUT_MS = 3000;
constexpr uint8_t MAX_RETRANSMIT = 4;
constexpr uint32_t SEPARATE_RESPONSE_MS = 30000;
}

