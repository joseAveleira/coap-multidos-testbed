// ESP32-S3 Mini numero 4. Perfil modificable independientemente.
#define DEVICE_ID 4
#define PROFILE_ID 4
#include "client.h"

Experiment experiment;
void setup() { experiment.setup(); }
void loop() { experiment.loop(); }
