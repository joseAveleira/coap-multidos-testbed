// ESP32-C6 (nucleo Arduino 3.x) numero 5. Perfil modificable independientemente.
#define DEVICE_ID 5
#define PROFILE_ID 5
#include "client.h"

Experiment experiment;
void setup() { experiment.setup(); }
void loop() { experiment.loop(); }
