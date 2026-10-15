# Actor CoAP para la campaña física

**Si eres la IA que va a operar el segundo ordenador, empieza por
[LEEME_IA.md](LEEME_IA.md).** Incluye la secuencia de ejecución, coordinación con
el PC de captura, revisión del piloto y entrega de evidencias.

Generador para el segundo ordenador, conectado a la red del servidor y los ESP32.
Requiere **Node.js 22 o posterior**, en Windows, Linux o macOS. No requiere npm.
Esta versión se ha probado en Windows con Node.js 22.19.0 y UDP en localhost;
queda pendiente calibrar tasas y pérdidas desde el segundo equipo físico.

El actor reproduce los dos comportamientos del manuscrito ampliado: peticiones
Block2 repetidas a `/large` y un flujo de GET a `/sensor`. El mismo equipo también
produce tráfico legítimo y descargas completas. Las etiquetas proceden del plan
experimental; no demuestran, por sí solas, que se haya degradado el servicio.

## Empezar con un piloto

Extrae `actor_coap_portable.zip` en el segundo ordenador y abre una terminal en
la carpeta que contiene `actor_coap.js`. En el repositorio, esa carpeta es
`scripts_esp32`.

1. Mantén el servidor activo y comprueba su IPv4 actual. Reserva esa dirección en
   el AP/router cuando sea posible. Servidor y actor deben poder comunicarse.
2. Ejecuta la comprobación, sustituyendo `IP_DEL_SERVIDOR`:

```text
node actor_coap.js check --server IP_DEL_SERVIDOR
```

Comprueba `/sensor` y los 32 bloques de `/large`, ETag y contenido. Es una prueba
benigna de 33 peticiones; no inicia la campaña.

3. En el PC servidor, arranca TShark **antes** de iniciar el actor. Desde una
   carpeta de captura nueva, elige la interfaz física con `tshark -D`:

```text
tshark -i INTERFAZ -f "udp port 5683" -s 0 -w fisica_001.pcapng
```

4. Arranca o reinicia las sesiones de los ESP32 y ejecuta el piloto desde el
   segundo ordenador:

```text
node actor_coap.js inspect --plan actor/ejemplos/piloto_180s.json
node actor_coap.js run --server IP_DEL_SERVIDOR --plan actor/ejemplos/piloto_180s.json --session piloto_001
```

El actor comprueba primero el servicio y espera diez segundos. Ejecuta el plan
de 180 segundos y cierra sus sockets. Después puedes detener la captura. El
nombre de sesión debe ser nuevo: los registros existentes no se sobrescriben.
Ctrl+C detiene los nuevos envíos, recoge respuestas pendientes y conserva un
resumen marcado `interrupted`.

El filtro captura CoAP de todos los participantes que llega/sale del servidor.
No contiene paquetes perdidos antes del punto de captura ni todos los reintentos
Wi-Fi. Conserva también los registros de las placas y los del servidor.

## Preparar sesiones y campañas

Estos comandos **solo generan planes, sin enviar tráfico**:

```text
node actor_coap.js plan --out planes/sesion_01.json --seed 2026 --duration 900 --pairs 6
node actor_coap.js campaign --out planes_campana --sessions 12 --seed 2026
```

El primer plan dura 15 minutos e incluye seis episodios de cada ataque, seis
ráfagas legítimas de sensor y seis episodios legítimos Block2 (tres descargas y
tres series de lecturas). Añade tráfico de base y guardas. La semilla varía el
orden, la posición, duración, tasa, tipos CON/NON, orden de bloques y tokens.
No hay un orden fijo por clase. `--scale 0.5` reduce las tasas de los episodios.
La semilla reproduce el plan, no los tiempos reales del sistema. Los MID y los
tokens iniciales se aleatorizan al abrir los sockets y se conservan en los logs;
los tokens tienen cuatro bytes, como los clientes físicos.

La campaña de ejemplo alterna 600, 900 y 1200 segundos y utiliza una semilla por
sesión. Es una propuesta inicial editable, no una garantía de tamaño suficiente
para publicar. `campaign.json` resume sesiones, cantidades, duraciones y hashes.
Se ejecuta cada plan explícitamente; no se lanzan campañas automáticamente.

```text
node actor_coap.js run --server IP_DEL_SERVIDOR --plan planes_campana/fisica_001.json --session fisica_001 --output registros_actor
```

**Duración de los ESP32:** desde el 14-10-2026, el firmware funciona sin límite
de tiempo mientras la placa está alimentada (`LAB_SESSION_MS = 0`) y reanuda la
sesión tras un corte de Wi-Fi. Basta con encenderlas antes de la captura. Después
de encenderlas o reiniciarlas, arranca una sesión de servidor nueva (ver
`../README.md`). El actor no controla los ESP32 ni su duración.

También conviene variar entre sesiones el número de placas activas, la asignación
de perfiles y su intensidad. Esos cambios se anotan en el manifiesto de captura;
no se deben dar por hechos a partir de la semilla del actor.

## Cargas incluidas

| Nombre | Comportamiento | Etiqueta del escenario |
|---|---|---|
| `baseline` | GET `/sensor`, 1–5 peticiones/s objetivo | Benigno |
| `benign_sensor_burst` | Ráfaga GET `/sensor`, con tasas solapadas con request flood | Benigno |
| `benign_block2_download` | Descargas completas, bloques secuenciales y token por transferencia | Benigno |
| `benign_block2_reads` | Lecturas de bloques con tasas y órdenes también usados por el ataque | Benigno |
| `block2_amplification` | GET repetidos que solicitan bloques de `/large` | Ataque Block2 |
| `request_flood` | GET repetidos a `/sensor`, CON o NON | Ataque de peticiones |
| `guard` | Sin envíos; permite recibir o vencer peticiones pendientes | Excluir del etiquetado del actor |

Los planes de referencia usan bloques de 1024 bytes y un recurso de 32768 bytes,
como el manuscrito ampliado. Cada petición recibe un bloque: una petición no
desencadena la descarga automática de todo el recurso. No se usa suplantación
de IP ni reflexión hacia otra víctima. Se mide la carga dirigida al servidor.

## Qué se controla y qué se mide

- Se mantienen cuatro sockets/puertos de origen durante toda la sesión. Se
  reparten entre las clases; un puerto no identifica un ataque. El manifiesto
  y los eventos guardan los extremos reales de cada flujo.
- Los MID no se reutilizan en un mismo socket antes de 247 segundos. Si no hay
  identificadores disponibles, el actor omite envíos y lo contabiliza.
- Los CON se correlacionan por MID y token. Los NON usan tokens únicos para
  correlacionar sus respuestas. La reutilización de token por episodio solo se
  permite con CON y queda indicada en el plan.
- Las descargas legítimas mantienen una única petición pendiente por socket y
  verifican todos los bloques y el contenido contra la precomprobación. Su tasa
  efectiva depende del RTT; puede quedar muy por debajo de la tasa objetivo.
  Descargas incompletas al cambiar de fase se contabilizan por separado.
- El resto de cargas usa un emisor abierto y acotado. No implementa el control
  de congestión/NSTART estándar ni retransmisiones automáticas. Es un generador
  experimental de mensajes CoAP, no una pila CoAP completa. Los ESP32 sí tienen
  su propia política de retransmisión, que debe describirse en la metodología.
- El ritmo usa un reloj monótono. Si el proceso se retrasa, omite posiciones de
  envío en lugar de compensarlas con una ráfaga. Se registran los envíos omitidos,
  la capacidad ocupada y la tasa realmente entregada a UDP por fase.
- Hay como máximo 512 solicitudes pendientes por socket. Los planes están
  acotados a 1000 peticiones/s, una hora y 600000 solicitudes programadas, además
  de la comprobación inicial. El destino es una sola IPv4 privada o loopback.
- Una respuesta ausente, incorrecta o tardía queda registrada. Entregar un
  datagrama a UDP no demuestra que haya llegado al servidor.
- Un cambio del contenido/ETag de `/large`, un error de socket o un fallo de
  registro detiene la ejecución y queda como fallo. Los timeouts de respuesta
  pueden ser un resultado del experimento y no convierten por sí solos la sesión
  en un fallo del generador.

## Registros para construir el dataset

Cada ejecución genera `registros_actor/NOMBRE/`:

| Archivo | Contenido |
|---|---|
| `manifest.json` | Versión, entorno, destino, política de reloj y hashes de fuentes/plan |
| `plan.json` | Programa previsto completo y sus parámetros |
| `events.jsonl` | Flujos, inicio/fin efectivo del planificador, guardas, descargas y contadores |
| `traffic.jsonl` | Cada intento de envío, resultado de UDP, respuesta, timeout o cancelación |
| `summary.json` | Estado final, tasas reales, resultados y avisos de calidad |
| `sha256.json` | Hashes de los archivos anteriores |

`phase_start` distingue el instante programado del instante en que el proceso
lo ejecutó. `phase_final` conserva el primer/último envío y respuesta y los
contadores definitivos tras las guardas. No etiquetes exclusivamente usando el
calendario previsto: puede haber arranques tardíos, pausas o sesiones interrumpidas.

Los eventos incluyen `epoch`, `wall_epoch`, `utc` y `mono_ms`. `epoch` se deriva
de un anclaje UTC y el reloj monótono; `wall_epoch` permite detectar ajustes del
reloj del sistema. **El script no sincroniza ni mide el desfase entre equipos.**
Sincroniza ambos equipos antes de la sesión y registra el método y la incertidumbre.
`--clock-note "método y comprobación realizados"` conserva esa nota, no certifica
la sincronización. `--start-at 2026-10-14T09:00:00+02:00` permite programar un
inicio futuro con zona explícita; sustituye la fecha por la que corresponda.

Cada `tx` tiene flujo, MID, token, bloque e identificador de petición; esto
permite contrastarlo con el PCAP capturado en el servidor y reconciliar relojes.
Si un envío no aparece en el PCAP, no se inventa una observación de tráfico.
El extractor de los 23 predictores está en `scripts_esp32/dataset/` del
repositorio completo; no forma parte de este ZIP. El controlador de
`scripts_esp32/campaign/` mide el desfase y coordina captura y actor por SSH.

Para el actor, excluye la precomprobación, las guardas y las ventanas que cruzan
fronteras de etiqueta o la incertidumbre de reloj. Esa exclusión no convierte
en malicioso el tráfico simultáneo de los ESP32. Agrupa y etiqueta por flujo
según el protocolo de extracción, manteniendo identificados los participantes.
Las etiquetas se relacionan con las respuestas de sus peticiones; una respuesta
tardía no hereda automáticamente la clase de la siguiente fase.

Conserva el PCAP completo para comparar después ventanas de 0,5, 1 y 2 segundos.
Los identificadores, IP, puertos, semillas, tiempos absolutos y nombres de fase
son metadatos de auditoría, no predictores de entrada al modelo. Mantén separadas
las sesiones en las particiones de entrenamiento y evaluación.

## Evidencia científica y límites

El paquete ayuda a responder a los comentarios 8, 9, 10, 11, 12 y 13 del revisor
1: permite duración y variabilidad, igual número de episodios de ambos ataques,
configuración por sesión, captura reutilizable para varios tamaños de ventana
y ejecución en otro equipo físico. Aún deben realizarse y documentarse las
sesiones; escribir el generador no equivale a haber validado la campaña.

El solapamiento de tráfico legítimo y de ataque es deliberado. Algunas cargas
pueden resultar indistinguibles con las variables disponibles; no se garantiza
una separación perfecta. Para afirmar degradación DoS hay que contrastar RTT,
pérdidas, disponibilidad y carga del servidor/ESP32 frente a periodos de base.

Antes de la campaña larga, revisa el piloto físico: tasas efectivas frente a
objetivos, `scheduler_skipped_slots`, timeouts, descargas verificadas, pérdidas
del capturador y `cache_evictions`/`mid_collisions` del servidor. El servidor
actual limita su caché de duplicados a 20000 entradas; las expulsiones bajo carga
son una característica del banco que debe medirse y documentarse.

## Verificación y procedencia

```text
node tests/actor.test.js
```

En PowerShell, para añadir tres pruebas breves con un servidor temporal en
localhost:

```powershell
$env:COAP_ACTOR_TEST_UDP = '1'
node tests/actor.test.js
```

Se probaron planificación/semillas, validaciones, ciclo de MID, correlación
CON/NON, rechazo de Block2 incorrecto, intercambio UDP, descargas completas,
registros/hashes y parada interrumpida. Estas pruebas no envían una campaña a
las placas ni sustituyen la validación física desde el segundo equipo.
La verificación completa consta de diez pruebas; todas han pasado en esta versión.

Implementación nueva basada en el servidor de este repositorio y en los dos
escenarios descritos en `Special_issue_Decai_CoAP_IGPL/main.tex`. La referencia
histórica del banco es `coap-multidos-testbed` v1.0.0; no se afirma reproducir
byte a byte sus sesiones.

Referencias de protocolo: [CoAP, RFC 7252](https://www.rfc-editor.org/rfc/rfc7252.html)
y [Block2, RFC 7959](https://www.rfc-editor.org/rfc/rfc7959.html).
