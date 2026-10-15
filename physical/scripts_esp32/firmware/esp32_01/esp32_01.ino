// ESP32-S3 Mini numero 1. Perfil modificable independientemente.
#define DEVICE_ID 1
#define PROFILE_ID 1
#include "client.h"

Experiment experiment;
void setup() { experiment.setup(); }
void loop() { experiment.loop(); }
