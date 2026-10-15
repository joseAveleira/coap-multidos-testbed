// ESP32-S3 Mini numero 2. Perfil modificable independientemente.
#define DEVICE_ID 2
#define PROFILE_ID 2
#include "client.h"

Experiment experiment;
void setup() { experiment.setup(); }
void loop() { experiment.loop(); }
