# Cliente CoAP05 instalado en la ESP32-C6

El 15-10-2026 se instaló este cliente, con autorización del responsable, en la
ESP32-C6 rev. 0.2 de MAC `58:8c:81:32:21:5c`. Se observó por Wi-Fi en
`10.37.225.20`, y el inventario físico confirmó las cinco placas. La consola
registró respuestas CoAP válidas y descargas completas de 32 bloques.
La evidencia de instalación, hashes y consola está en
`test/c6_micropython_20261015/`, desde la raíz del repositorio.

El proyecto Arduino de `firmware/esp32_05/` también compila, pero **no es el
firmware utilizado por esta C6**. Las cuatro S3 conservan sus clientes Arduino.

La imagen instalada es la oficial `ESP32_GENERIC_C6-20260824-v1.29.0.bin`, de
1967664 bytes, para ESP32-C6 y 4 MB de flash. La inspección de esptool confirmó
cabecera compatible con la revisión 0.2. La placa tenía una aplicación Zigbee;
hay una copia privada completa de sus 4 MB en `.local/` del PC de preparación.
La instalación sustituyó esa aplicación por MicroPython 1.29.0 y el cliente
CoAP sobre Wi-Fi. Esptool verificó el hash de los bytes escritos. Se usaron
esptool 5.4.0 y mpremote 1.29.0; no se usa Zigbee en esta adquisición.

Después de cerrar las capturas se recuperaron `main.py` y `coap_wire.py` de la
placa: sus hashes coinciden con los archivos del repositorio. Se guardaron
también los hashes de ambos registros de consola. Esta comprobación se hizo
fuera de la adquisición y después se reinició el mismo cliente.

## Comportamiento instalado

- Solo cliente CoAP legítimo por Wi-Fi, identidad 05 y UDP local 56835.
- Consultas NON de `/sensor` cada 500–700 ms.
- Episodios de 2–5 s, separados por pausas de 8–20 s: consultas rápidas,
  lecturas repetidas de bloques o descargas secuenciales de `/large`.
- Consultas/lecturas rápidas NON; descargas CON con un token por transferencia,
  bloques de 1024 bytes y comprobación de ETag. Una descarga tiene una petición
  en vuelo; las tasas efectivas dependen de las respuestas.
- Máximo 64 solicitudes pendientes; timeout de 3 s, sin retransmisión. Registra
  objetivos de tasa, envíos, respuestas, timeouts y huecos de planificación.
- Recuperación de Wi-Fi y órdenes serie START/STOP/STATUS. Funcionamiento sin
  límite de duración mientras esté alimentada.

La ficha del banco identifica esta implementación y sus hashes por separado
de Arduino. Las tasas son objetivos; las respuestas, timeouts y descargas
efectivas quedan registradas durante la adquisición.

## Archivos y validación

`main.py` contiene el cliente, `coap_wire.py` el códec y `config.example.py` la
plantilla. Las credenciales deben estar en `config_local.py` **solo en la placa
o en una carpeta local ignorada**. No publicar imágenes que incluyan credenciales.

```powershell
python scripts_esp32/tests/c6_protocol_test.py
```

La prueba con el servidor Node real en localhost verificó 33 peticiones, una
descarga íntegra de 32768 bytes y seis rechazos de mensajes malformados. El
resultado está en `test/c6_protocol_validation.json`. La ejecución posterior
en la placa tiene su propia evidencia de consola e inventario físico. Los
timeouts anteriores al arranque del servidor no se atribuyen a la campaña:
para analizar cada sesión se utilizan sus límites temporales y PCAP.

Fuentes: [imagen e instalación oficiales](https://micropython.org/download/ESP32_GENERIC_C6/)
y [API WLAN](https://docs.micropython.org/en/v1.28.0/library/network.WLAN.html).
