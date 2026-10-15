// ESP32-S3 Mini numero 3. Perfil modificable independientemente.
#define DEVICE_ID 3
#define PROFILE_ID 3
#include "client.h"

Experiment experiment;
void setup() { experiment.setup(); }
void loop() { experiment.loop(); }
