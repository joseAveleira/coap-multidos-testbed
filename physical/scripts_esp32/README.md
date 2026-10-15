# Banco físico CoAP: cuatro ESP32-S3, un ESP32-C6 y servidor Node.js

Las cuatro S3 utilizan los proyectos Arduino; la C6 utiliza el [cliente MicroPython](firmware/c6_micropython/README.md), instalado y observado por Wi-Fi el 15-10-2026. También se conserva el proyecto Arduino de la C6 como alternativa compilada. El servidor se ejecuta en el ordenador y no requiere paquetes npm. Este montaje conserva los recursos y tipos de tráfico legítimo del simulador del artículo: consultas cortas, ráfagas de consultas, descargas completas Block2, lecturas de bloques y sondas.

## Montaje

Para el segundo ordenador ya está disponible el [actor de campaña CoAP](actor/README.md),
con planes reproducibles, los dos ataques del artículo, cargas legítimas comparables
y registros por petición. Entrada: `node actor_coap.js --help`. El paquete portátil
se genera con `python actor/empaquetar.py`. Para la IA que lo ejecute desde ese
equipo, empieza por [LEEME_IA.md](actor/LEEME_IA.md), incluido también en el ZIP.

```text
ESP32 01 ─┐
ESP32 02 ─┤ Wi-Fi      Aveleira        Wi-Fi          Este PC
ESP32 03 ─┤──────────── 2,4 GHz ───────────────────── servidor CoAP
ESP32 04 ─┤                                          + TShark/Wireshark
ESP32 05 ─┘ (C6, MicroPython 1.29.0)
                         │
                  Otro equipo (fase de ataques)
```

El PC es el servidor de recursos de una aplicación IoT. Los ESP32 son consumidores: consultan un valor de proceso y recuperan una representación de configuración. El valor de proceso y la configuración son sintéticos, con formato documentado; el hardware, las comunicaciones y los tiempos observados serán reales al ejecutar las pruebas. No hacen falta sensores, LEDs ni conexiones a GPIO para esta primera campaña.

## Qué hace cada placa

| Placa | Cliente instalado | Función de aplicación | Tráfico por defecto |
|---|---|---|---|
| 01 | `firmware/esp32_01/esp32_01.ino` | Controlador que consulta un valor central de proceso. | GET `/sensor` CON cada 750–1000 ms. |
| 02 | `firmware/esp32_02/esp32_02.ino` | Cliente que aumenta la frecuencia de lectura durante eventos de interés. | GET CON cada 2000–2600 ms; cada 30–40 s entra en una ráfaga de 3 s, con GET NON separados al menos 100 ms. |
| 03 | `firmware/esp32_03/esp32_03.ino` | Cliente que sincroniza una tabla de configuración. | GET `/sensor` cada 2500–3000 ms; descarga `/large` a los 5–10 s y después cada 60–75 s. Recorre los 32 bloques en orden, con un mismo token por transferencia y al menos 20 ms entre bloques. |
| 04 | `firmware/esp32_04/esp32_04.ino` | Monitor de disponibilidad que también comprueba fragmentos de configuración. | GET `/sensor` cada 1000–1200 ms; cada 20–25 s lee seis veces un bloque elegido, con al menos 100 ms entre lecturas. |
| 05 | `firmware/c6_micropython/main.py` | Pasarela mixta en C6. | Telemetría NON cada 500–700 ms y episodios rápidos mixtos. |

En las S3, el tráfico de fondo mantiene una petición pendiente por dispositivo; los episodios rápidos tienen su propio límite descrito a continuación. Las esperas, pérdidas y retransmisiones afectan a las tasas efectivas. Una lectura de bloques pendiente en la placa 04 puede retrasar la siguiente sonda. La C6 admite hasta 64 peticiones pendientes en total y una por descarga secuencial, con timeout de 3 s y sin retransmisión; sus consultas y lecturas rápidas son NON, y sus descargas, CON.

### Episodios rápidos legítimos

Además del tráfico anterior, las placas 02, 03 y 04 tienen episodios rápidos, inspirados en los clientes .10, .11 y .12 del simulador original. En el original, esos clientes alternaban unas 2 peticiones/s con ráfagas benignas de cientos de peticiones/s, de modo que la tasa por sí sola no separaba el tráfico legítimo de los ataques.

| Placa | Episodio rápido | Tasas posibles (pet/s) | Tipo |
|---|---|---|---|
| 01 | Ninguno: sonda constante, como el cliente .20 | — | — |
| 02 | GET `/sensor` | 40, 80, 150, 250 | CON o NON al azar |
| 03 | Descargas completas de `/large` seguidas, un token por transferencia | 20, 50, 100, 200 | CON |
| 04 | Lecturas repetidas de un bloque elegido al azar | 20, 50, 100, 200 | CON o NON al azar |

Cada episodio dura 2–5 s y se repite cada 8–20 s (en torno al 20 % del tiempo, como en el original). Usa ritmo fijo con hasta 128 peticiones en vuelo, timeout de 3 s y sin retransmisión, igual que el actor. El tráfico de fondo sigue activo durante el episodio. La planificación usa su propia semilla, de modo que el tráfico de fondo conserva la secuencia validada.

Las tasas son menores que las del simulador (650 y 500 pet/s). En la calibración del 14-10-2026 con el punto de acceso Aveleira, por encima de ~300 pet/s por placa fallaban los envíos (cola de transmisión Wi-Fi del ESP llena) y los timeouts subían al 5–10 %. Cada episodio registra en la consola `fast_start` (tipo, tasa, duración) y `fast_end` (enviadas, respondidas, timeouts, errores, envíos fallidos y huecos saltados).

Los perfiles de las placas son legítimos. La quinta placa C6 ya funciona como pasarela mixta mediante MicroPython 1.29.0, exclusivamente sobre Wi-Fi. En su validación física se observaron respuestas válidas y descargas completas de 32 bloques. Su firmware anterior está respaldado de forma privada. El equipo actor añade los dos ataques y sus propias cargas legítimas comparables. Los pilotos previos guardados documentan una y cuatro S3; cada adquisición conserva su inventario real.

## 1. Arrancar el servidor

Necesitas Node.js con soporte de los módulos estándar utilizados (recomendado Node.js 22 o posterior). Desde esta carpeta:

```bash
node servidor/server.js --host 0.0.0.0 --session fisica_001 --seed 2026
```

Escucha UDP en el puerto 5683. Deja el servidor funcionando y detenlo con Ctrl+C al acabar las cuatro placas. Si quieres una duración fija, por ejemplo 15 minutos:

```bash
node servidor/server.js --host 0.0.0.0 --session fisica_002 --seed 2027 --duration 900
```

Los ESP funcionan por defecto sin límite de tiempo, hasta que se apagan. El inicio de cada placa no está sincronizado por el arranque del servidor.

**Arranca una sesión de servidor nueva después de encender, reiniciar o flashear las placas.** El servidor recuerda durante 247 s el MID de cada petición CON (deduplicación de CoAP), y un ESP que se reinicia elige al azar el primer MID. Si ese MID cae dentro del rango que la placa usó antes del reinicio, el servidor responde RST y cuenta `mid_collisions`. En la calibración del 14-10-2026 ocurrió así: 975 colisiones tras flashear con el servidor en marcha.

`0.0.0.0` es la dirección de escucha; en los ESP escribe la IPv4 real del PC en la red de pruebas, por ejemplo `192.168.1.100`. Reserva esa dirección en el DHCP del router y permite UDP/5683 hacia el PC en esa red. Los clientes y el PC deben poder comunicarse: revisa que el AP no tenga aislamiento entre clientes o red de invitados.

Recursos:

| Recurso | Respuesta |
|---|---|
| GET `/sensor` | `temperature=23.6` (ejemplo). Valor central emulado que cambia cada segundo; texto plano y Max-Age 0. |
| GET `/large` | Representación estable de 32 768 bytes. Block2 con 1024 bytes por defecto; admite tamaños de 16 a 1024 bytes. Content-Format 42, ETag y Size2. |
| GET `/.well-known/core` | Descubrimiento de los dos recursos anteriores. |

La representación grande contiene un patrón alfabético determinado por `--seed`; sirve para comprobar integridad sin almacenar los 32 KiB en el ESP. La placa 03 verifica todos los bytes, el orden, la longitud y que el ETag permanezca estable. Cada petición devuelve un único bloque, igual que en el simulador. Cambiar la semilla del servidor no exige recompilar el cliente.

## 2. Configurar y cargar los ESP32

Instala el soporte **esp32 by Espressif Systems** en Arduino IDE. Abre un proyecto por placa, por ejemplo `firmware/esp32_01/esp32_01.ino`. Los archivos de apoyo ya están junto al sketch y no necesitas instalar una librería CoAP externa.

En cada proyecto, copia [config_local.example.h](firmware/config_local.example.h)
como `config_local.h` junto al sketch y completa el mismo contenido de red:

```cpp
#pragma once
#define LAB_WIFI_SSID "NOMBRE_DE_LA_RED"
#define LAB_WIFI_PASSWORD "CLAVE_DE_LA_RED"
#define LAB_SERVER_IP "192.168.1.100"
```

Usa `config_local.h` para las credenciales reales; `config.h` conserva valores
de ejemplo. `config_local.h` se conserva al regenerar proyectos y está excluido
del control de versiones. Nunca se imprime la clave en los registros.

Selecciona la placa exacta si figura en el IDE. **“ESP32-S3 Mini” no identifica de forma unívoca la memoria ni el fabricante.** Si utilizas el perfil genérico *ESP32S3 Dev Module*, configura tamaño y modo de flash según tu módulo. El firmware no utiliza PSRAM ni pines específicos. Para un S3 con USB nativo, activa *USB CDC On Boot* y usa el puerto de esa placa. Con un adaptador UART, la configuración del puerto/CDC puede ser distinta. El monitor serie funciona a **115200 baudios**. Registra la versión del núcleo Arduino y la selección de placa que uses.

Carga cada sketch en su placa correspondiente y marca físicamente las placas 01–05. La identidad está en `DEVICE_ID`; `PROFILE_ID` permite cambiar de comportamiento sin cambiar la identidad. Puedes rotar perfiles entre placas en nuevas sesiones.

Para la C6 se ha comprobado la compilación de `esp32_05` con pioarduino
55.03.312-1, Arduino 3.3.12, USB Serial/JTAG y flash de 4 MB. El registro,
particiones y hashes están en `test/c6_preparacion_20261015/`. La imagen ocupa
aproximadamente 990 KB y la RAM estática 123596 bytes. **Todavía no está
flasheada ni validada en red**. Confirmar el puerto y la MAC antes de cargarla:

```powershell
pio run -d scripts_esp32 -e esp32_05 -t upload --upload-port PUERTO_C6
```

Este comando se ejecuta desde la raíz del repositorio. Las imágenes compiladas
contienen la configuración Wi-Fi privada y se mantienen fuera de Git.

Al conectar con Wi-Fi, el dispositivo imprime `ready`, su IP y su puerto local (`56831` a `56835`). Cinco segundos después inicia automáticamente una sesión **sin límite de tiempo**: basta con alimentar la placa, sin USB de datos ni monitor serie. Para limitar la sesión, compila con `-DLAB_SESSION_MS=600000` (milisegundos). En el monitor, con fin de línea “Nueva línea”, puedes enviar:

```text
START
STOP
STATUS
```

`START` comienza una nueva sesión; si ya había una, registra su cancelación. `STOP` cancela también un arranque automático pendiente. Para comenzar solo mediante órdenes, cambia `AUTO_START` a `false` en `config.h` antes de cargarlo.

Si se pierde Wi-Fi, se registra `wifi_disconnected` y se detiene la sesión. Al reconectar se registra `session_resume_scheduled` y, cinco segundos después, empieza una sesión nueva. Así, una placa alimentada sin USB no se queda callada tras un corte. Si antes se envió `STOP`, no se reanuda. El corte queda visible en el PCAP como un hueco en el tráfico de esa placa.

## 3. Comprobación previa y captura

Con el servidor arrancado, desde este PC o desde otro equipo de la red:

```bash
node servidor/comprobar.js 192.168.1.100
```

Comprueba una lectura de `/sensor` y una descarga completa de `/large`, incluyendo tamaño, bloques e integridad. No añade ataques. Si se ejecuta contra el propio PC, esta prueba solo verifica el servicio local; ejecutarla desde el otro equipo verifica además conectividad física.

Para la captura del experimento, usa la interfaz física del PC servidor. En TShark:

```bash
tshark -D
mkdir capturas
tshark -i NUMERO_INTERFAZ -f "udp port 5683" -w capturas/fisica_001.pcapng
```

Sustituye `NUMERO_INTERFAZ` por el identificador Ethernet o Wi-Fi que corresponda. Arranca la captura antes de iniciar el tráfico de los ESP y detenla después. Guarda el resumen de TShark, incluidos paquetes descartados por la captura. Esta ubicación registra los paquetes que llegan/salen del PC; no registra por sí sola todas las retransmisiones de la capa Wi-Fi.

El servidor crea `servidor/registros/fisica_001/` con:

- `manifest.json`: semilla, parámetros, versión de Node y momento de arranque.
- `server.jsonl`: contadores acumulados cada segundo con hora UTC/epoch.
- `summary.json`: resumen al cerrar normalmente.

El nombre de sesión debe ser nuevo; se evita sobrescribir una grabación. Con `--requests` se añade una entrada por petición procesada. Es útil al depurar, pero aumenta el coste de registro: los PCAP son la fuente del tráfico y los registros no los sustituyen. La cola de registro está limitada y contabiliza entradas descartadas. El servidor contabiliza envíos entregados a la pila UDP, lo que no demuestra recepción en el ESP.

El monitor serie del ESP produce JSON por línea: inicio, respuestas, tiempos de espera, errores, descargas verificadas y resumen. `ms` es tiempo desde el arranque del ESP, **no UTC**. `elapsed_ms` se mide desde el primer envío e incluye retransmisiones si las hubo; para RTT sin retransmisiones selecciona `retries=0`. Conserva estos registros y las correspondencias entre dispositivo, perfil e IP.

Para etiquetar ataques en una fase posterior harán falta eventos externos de inicio/fin y la identidad del flujo atacante. El servidor no deduce etiquetas maliciosas de la tasa de peticiones ni del dispositivo. El [extractor PCAP → CSV](dataset/README.md) genera las mismas 23 variables en ventanas de 0,5/1/2 s; los [dos pilotos ya convertidos](../recursos/dataset_fisico/README.md) conservan su trazabilidad.

## 4. Parámetros y continuidad con el simulador

Los ritmos y episodios rápidos están en `profiles.h`; duración, semilla de planificación, Block2 y ahorro Wi-Fi, en `config.h`. La semilla hace reproducible la planificación de pausas, pero la temporización real también depende de las respuestas y del Wi-Fi. Los tokens y el punto inicial del contador MID se aleatorizan al arrancar. En el tráfico de fondo, una petición CON se retransmite con el mismo MID/token: espera inicial 2–3 s, duplicada en cada reintento, hasta cuatro retransmisiones. Las NON no se retransmiten y tienen una espera de aplicación de 3 s. Los episodios rápidos no retransmiten. Una sesión puede terminar cancelando una petición pendiente; esa cancelación se registra por separado de los timeouts.

Hay una protección contra la reutilización de MID: un MID solo se repite si en los últimos 248 s se asignaron más de 65 000, y entonces la petición se omite y se cuenta en `mid_exhausted`. Así no se reutiliza un MID dentro del EXCHANGE_LIFETIME (247 s) del servidor. La protección solo cubre un mismo arranque; para los reinicios, consulta la regla del apartado 1.

La recepción UDP usa una tarea propia (`link.h`). lwIP del núcleo Arduino solo guarda 6 datagramas por socket (`CONFIG_LWIP_UDP_RECVMBOX_SIZE`), y la Wi-Fi entrega las respuestas en ráfagas agregadas. Leer desde `loop()`, que duerme 1 ms por vuelta, perdía el 25–30 % de las respuestas a 200 pet/s. La tarea vacía cada datagrama al llegar en un anillo de 64; si este se llenara, el resumen lo contaría en `rx_overflow`.

El servidor admite ACK inmediato y el cliente reconoce también ACK vacío y respuesta separada. Se valida la IP/puerto de origen, token, MID cuando corresponde y opciones Block2. Se rechazan opciones críticas no soportadas, tamaños Block2 no válidos y bloques fuera del recurso. La caché de duplicados CON dura 247 s y está limitada a 20 000 entradas; su contador de expulsiones permite detectar cuándo se alcanzó ese límite.

Es un subconjunto CoAP/UDP para este experimento: GET, CON/NON, ACK/RST y Block2. No implementa Observe, DTLS, Block1, proxy ni una pila CoAP completa. Sigue el enfoque sin dependencias del generador original. Respecto a aquel generador, añade manejo de pérdidas/retransmisiones, ETag, deduplicación y validación de bloques; por ello no reproduce byte a byte las capturas antiguas. Mantén el dataset físico separado del original y documenta estas diferencias.

El código de referencia revisado fue `testbed/run_session.js`, etiqueta `v1.0.0`, de [coap-multidos-testbed](https://github.com/joseAveleira/coap-multidos-testbed/blob/v1.0.0/testbed/run_session.js).

## 5. Mantenimiento y alternativa PlatformIO

El código mantenido está en `firmware/base/`. Las carpetas Arduino son copias del código base. `esp32_05` corresponde al C6 y necesita la plataforma especificada en su entorno, distinta de la de S3. Se puede generar solo una con `python preparar_sketches.py --device 5`; no regeneres las demás con `--force` si contienen cambios pendientes. Tras cambiar la base:

```bash
python3 preparar_sketches.py
```

Si hay cambios en una copia, el comando se detiene para no borrarlos. `--force` reemplaza los `.ino` y `.h` generados, pero conserva `config_local.h`. No modifiques solo la base esperando que cambien automáticamente los proyectos ya generados.

Para PlatformIO, configura `firmware/base/config_local.h` y usa el entorno de cada placa:

```bash
pio run -e esp32_01
pio run -e esp32_01 -t upload --upload-port PUERTO
pio device monitor --port PUERTO --baud 115200
```

Repite con `esp32_02`, `esp32_03` y `esp32_04`. El perfil genérico suministrado utiliza 4 MB de flash, modo DIO, sin PSRAM y USB CDC; comprueba su correspondencia con tu módulo. El paquete de plataforma se fija a `espressif32@7.0.1` para evitar cambios inadvertidos de herramientas. La compilación necesita los paquetes de PlatformIO para **ESP32-S3**; tener instalado solo el compilador del ESP32 clásico no basta.

## Verificación

```bash
python3 verificar.py
python3 verificar.py --udp
```

La primera orden requiere Node.js, Python 3 y g++. Comprueba el servidor con transporte en memoria, el formato de mensajes del firmware y los cuatro perfiles C++ con Arduino/Wi-Fi/reloj simulados. Comprueba una pérdida seguida de retransmisión, descarga íntegra, fin de sesión con `LAB_SESSION_MS`, episodios rápidos completos en los perfiles 2–4, reanudación tras perder la Wi-Fi y que un `STOP` manual impide reanudar. `--udp` añade los mismos casos del servidor mediante sockets locales reales.

Hay siete adquisiciones físicas verificadas: tres pilotos y cuatro capturas de diez minutos con las cinco placas y el actor Arch. Contienen 769063 paquetes CoAP; la campaña nueva ejecutó 24 episodios de cada ataque. Los PCAP y CSV a 0,5/1/2 s están auditados. La C6 utiliza MicroPython 1.29.0. Consulta [el resumen de datos](../recursos/dataset_fisico/README.md) y la [guía de campaña](campaign/README.md).

Referencias de implementación: [CoAP, RFC 7252](https://www.rfc-editor.org/rfc/rfc7252.html), [Block2, RFC 7959](https://www.rfc-editor.org/rfc/rfc7959.html), [Wi-Fi de Arduino-ESP32](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html), [USB CDC en ESP32-S3](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/usb_cdc.html), [captura en el equipo servidor](https://wiki.wireshark.org/CaptureSetup/Ethernet).
