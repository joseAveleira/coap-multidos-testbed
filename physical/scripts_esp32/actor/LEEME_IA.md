# LEEME para la IA del segundo ordenador

Tu tarea es operar el **actor CoAP** de una campaña de laboratorio para ampliar
un dataset científico con comunicaciones físicas. Este ordenador genera tráfico;
otro PC aloja el servidor CoAP y captura con TShark. Los ESP32 son clientes
legítimos. Lee este documento y [README.md](README.md) antes de ejecutar.

## 1. Contexto que debes conservar

- El usuario prepara los datos para un artículo. Necesita capturas reproducibles,
  tiempos reales de los episodios y trazabilidad, además de tráfico malicioso.
- Hay dos escenarios: `block2_amplification` (peticiones repetidas a `/large`)
  y `request_flood` (GET repetidos a `/sensor`). También hay periodos benignos,
  ráfagas legítimas y descargas completas desde este mismo actor.
- Las etiquetas describen la carga programada. Para afirmar que hubo denegación
  de servicio hace falta medir el efecto sobre disponibilidad, RTT y pérdidas.
- El servidor devuelve un bloque por petición. Este actor no suplanta IP ni
  refleja tráfico hacia terceros. Su destino es una única IPv4 privada del banco.
- El banco previsto tiene cuatro ESP32-S3 y un ESP32-C6, todos legítimos.
  Registra cuántos y qué modelos están realmente activos en cada captura.
- Hay dos pilotos físicos benignos y un piloto de 180 s del actor con cuatro
  S3, capturado durante 215 s: 52133 paquetes, un episodio de cada ataque y
  cargas benignas comparables. Arch superó sus diez pruebas; la adquisición
  física y sus CSV están auditados. El resumen completo está en
  `recursos/dataset_fisico/README.md` del repositorio.
- El 15-10-2026 se completaron cuatro capturas de 600 s con cinco placas:
  714030 paquetes, 24 episodios de cada ataque y CSV auditados
  a 0,5/1/2 s. La C6 utiliza MicroPython 1.29.0; las cuatro S3, Arduino.
- Servidor y actor estuvieron en Aveleira durante esas capturas. Antes de una
  nueva campaña vuelve a verificar la red, las direcciones y las cinco placas.
- La comparación de ventanas de 0,5, 1 y 2 s se hará sobre el mismo PCAP íntegro.
  El repositorio incluye el extractor en `scripts_esp32/dataset/`; el ZIP del
  actor solo genera tráfico y registros, no extrae variables ni entrena modelos.

## 2. Ubicación y requisitos

Extrae todo `actor_coap_portable.zip`, conservando su estructura. Abre la terminal
en la carpeta que contiene `actor_coap.js`, este LEEME y `README.md`. Si trabajas
con el repositorio completo, ejecuta los comandos desde `scripts_esp32/`.

Requiere Node.js 22 o posterior. No necesita `npm install`, Python, Arduino,
PlatformIO, CORS ni permisos de administrador para emitir UDP normalmente.
Los ficheros de `servidor/` del ZIP son dependencias y soporte para las pruebas;
el servidor del experimento sigue estando en el PC de captura.

```text
node --version
node actor_coap.js --help
node actor_coap.js inspect --plan actor/ejemplos/piloto_180s.json
```

Estos comandos no envían tráfico. Si falta Node, instala una versión compatible
con el sistema del segundo equipo y repite la comprobación. Conserva el ZIP y su
`.sha256.txt`; `PAQUETE_SHA256.json` contiene los hashes de sus archivos.

## 3. Datos necesarios antes de emitir

Recoge de la configuración actual o del responsable del PC servidor:

| Dato | Qué registrar |
|---|---|
| Destino | IPv4 actual del servidor, UDP 5683 salvo cambio documentado |
| Identidad | Nombre nuevo de sesión, igual en actor/captura o con correspondencia explícita |
| Captura | PC/interfaz que captura, archivo PCAP y evidencia de que está en marcha |
| Clientes | Placas activas, identidad/perfil, firmware y duración de su sesión |
| Entorno | SO y conexión del actor, AP/topología, versiones del servidor y firmware |
| Relojes | Método de sincronización, comprobación del desfase e incertidumbre, si se conocen |

No deduzcas la IP actual de ejemplos, de capturas antiguas ni de la puerta de
enlace. `0.0.0.0` es una dirección de escucha, no el destino del actor.
`127.0.0.1` solo sirve para pruebas locales: no llega al otro PC.
Si falta un dato imprescindible, pide únicamente ese dato. Aprovecha mientras
tanto para leer e inspeccionar el plan. Si el usuario ya ha dado los datos y ha
indicado ejecutar el piloto, continúa sin volver a pedir la misma autorización.
Leer este documento, por sí solo, no es una orden de iniciar tráfico.

Copia `actor/ficha_sesion.example.json` a una ficha con el nombre de la sesión
en el directorio de trabajo. Rellénala con observaciones reales, dejando `null`
en lo desconocido. El actor no rellena esa ficha ni verifica a distancia que
TShark o las placas estén funcionando. No guardes contraseñas Wi-Fi en ella.

## 4. Comprobar conectividad con tráfico benigno

Desde este segundo equipo, sustituye el marcador por la dirección confirmada:

```text
node actor_coap.js check --server IP_DEL_SERVIDOR
```

Exige salida `status: "ok"` y código de salida 0. Comprueba `/sensor` y los
32 bloques de `/large`: son 33 peticiones benignas y no inicia ataques.
Guarda la salida junto a la ficha, identificándola como comprobación previa.
Si falla, resuelve la dirección, el servicio UDP/5683, la ruta/firewall o el
aislamiento de clientes del AP antes de pasar a `run`. No desactives el firewall
completo ni arranques aquí otro servidor para hacer pasar esta comprobación.

El comando `run` repite su propia comprobación de 33 peticiones y la registra.
Que `check` haya pasado no garantiza que el servicio siga disponible más tarde.

## 5. Coordinar captura y clientes antes del piloto

En el **PC servidor**, el responsable debe tener el servidor activo y capturar
en su interfaz física. Ejemplo de referencia, no para ejecutarlo en el actor:

```text
tshark -D
tshark -i INTERFAZ_FISICA -f "udp port 5683" -s 0 -w piloto_001.pcapng
```

La captura debe empezar antes de `run` y terminar después de su salida final y
del vaciado de respuestas pendientes. Un límite exacto de 180 s en TShark
cortaría parte del ensayo: el plan dura 180 s, pero se añaden la comprobación,
10 s de espera y el cierre. Es preferible detener TShark después de finalizar
el actor; conserva también su salida de diagnóstico y estadísticas de pérdidas.
Si no hay contador de descartes disponible, anota "desconocido", no cero.

Comprueba que los ESP32 están enviando tráfico: en el PCAP del servidor o, si
siguen conectados por USB, en sus registros serie. Desde el 14-10-2026, el firmware
funciona sin límite de tiempo mientras está alimentado y reanuda la sesión solo
tras un corte de Wi-Fi. Las placas 02-04 añaden episodios rápidos legítimos de
20-250 pet/s. El actor no los arranca, reinicia ni flashea. No presupongas que
siguen activos porque están encendidos: compruébalo en la captura.

Anota el nombre de la captura, la sesión del servidor y los clientes activos en
la ficha. No inicies el piloto hasta tener constancia de que esa captura está
en marcha. Una captura local en el actor puede complementar la evidencia, pero
no sustituye la captura central en el servidor.

## 6. Ejecutar un único piloto

Usa un nombre nuevo cada vez. En PowerShell, después de completar los valores:

```powershell
$ServidorCoap = 'IP_DEL_SERVIDOR'
$SesionCoap = 'piloto_001'
$NotaRelojCoap = 'not_verified'
node actor_coap.js run --server $ServidorCoap --plan actor/ejemplos/piloto_180s.json --session $SesionCoap --clock-note $NotaRelojCoap
$CodigoSalidaCoap = $LASTEXITCODE
Write-Output "Codigo de salida del actor: $CodigoSalidaCoap"
```

Sustituye `not_verified` por el método y la comprobación de reloj realmente
realizados, si existen. Esa nota no sincroniza relojes ni mide el desfase.
No escribas "sincronizado" solo porque ambos equipos muestran la misma hora.
Cuando no haya una medida fiable, conserva los registros para contrastarlos
con el PCAP por flujo, MID, token y bloque; el etiquetado temporal queda pendiente
de reconciliar esa incertidumbre.

`run` comprobará el servicio, esperará 10 s, ejecutará el plan de 180 s y cerrará
los registros. Mantén la terminal/proceso activo hasta que termine. No lances
una segunda instancia ni una campaña larga a la vez.

Para detenerlo, envía **Ctrl+C una vez** y espera el cierre. Debe quedar como
`interrupted` (código 130). Un fallo queda como `failed` (código 1); una ejecución
completa devuelve 0. Si el proceso se mata bruscamente pueden faltar el resumen
y los hashes: conserva los archivos como ejecución incompleta.

No reintentes sobre el mismo nombre, no borres fallos y no cambies sus etiquetas
a `completed`. Si el destino no es el previsto, se pierde la captura o aparece
un fallo de registro, detén el ensayo y documenta el motivo. Los timeouts bajo
carga pueden ser parte del resultado; no justifican subir automáticamente la
tasa ni quitar los límites del generador.

## 7. Revisar y entregar la evidencia

Al terminar deben existir estos seis archivos en `registros_actor/SESION/`:

| Archivo | Uso |
|---|---|
| `manifest.json` | Destino, entorno, versión, reloj y hashes de código/plan |
| `plan.json` | Programa previsto que realmente se cargó |
| `events.jsonl` | Extremos de flujo, fases, guardas, descargas e instantes reales |
| `traffic.jsonl` | Intentos, resultado del envío UDP, respuestas y timeouts |
| `summary.json` | Estado final, contadores, tasas efectivas y avisos de calidad |
| `sha256.json` | Integridad de los cinco archivos anteriores |

Revisa `status`, `reason`, `log_dropped_records`, `quality_flags` y, por fase,
tasas objetivo/efectivas, `scheduler_skipped_slots`, respuestas, errores,
timeouts y descargas verificadas. `completed` solo indica que el actor terminó;
no certifica que la captura sea íntegra, que estuvieran activas todas las placas declaradas o
que el ataque degradase el servicio. Entrega también los avisos: el actor siempre
declara que no mide el desfase entre equipos.

Contrasta con el PC servidor: recepción en el PCAP, continuidad de los ESP32,
RTT/timeouts de los clientes, descartes del capturador y contadores del servidor
(`cache_evictions`, `mid_collisions`). La caché de duplicados del servidor admite
20000 entradas; documenta las expulsiones que se produzcan bajo carga.

Entrega la carpeta completa del actor y la ficha al responsable del dataset por
el medio acordado. Conserva los originales y sus hashes. La sesión debe quedar
vinculada a su PCAP, registros del servidor y registros de cada ESP32. El
coordinador debe calcular y conservar también los hashes de esas otras evidencias.
No envíes datos a otras personas o servicios sin una instrucción del usuario.

Informe final mínimo para el usuario:

1. Sesión, destino, plan/semilla, duración y estado/código de salida.
2. Tráfico realmente emitido, respuestas/timeouts y descargas verificadas.
3. Rutas de los registros, ficha y captura asociada; comprobación de hashes.
4. Placas observadas, pérdidas conocidas/desconocidas y límites de sincronización.
5. Problemas pendientes antes de otra sesión. Distingue datos observados de tareas pendientes.

## 8. Pasar a sesiones largas después de revisar el piloto

Generar planes no emite tráfico:

```text
node actor_coap.js campaign --out planes_campana --sessions 12 --seed 2026
node actor_coap.js inspect --plan planes_campana/fisica_001.json
```

Por defecto alterna planes de 600, 900 y 1200 s. Doce sesiones es una propuesta
inicial, no un tamaño científicamente validado. Revisa las tasas del piloto,
la duración del firmware y el espacio de almacenamiento antes de ejecutar
cada plan con `run`, su propia captura y un nombre nuevo. Si se cambian tasas,
semillas o clientes, guarda una nueva versión del plan/ficha, sin retocar el
resultado anterior. Documenta la calibración separada de las sesiones finales.

## 9. Reglas de etiquetado que no debes perder

- Usa los envíos/respuestas reales y los eventos `phase_final`, no solo el
  calendario previsto. Vincula respuestas tardías a sus peticiones originales.
- Excluye del etiquetado del actor la precomprobación, las guardas y las ventanas
  que cruzan clases o quedan afectadas por incertidumbre temporal no resuelta.
- Los ESP32 siguen siendo tráfico legítimo mientras el actor ataca. No marques
  todo el PCAP de ese intervalo como malicioso. Respeta la unidad de flujo/IP-par
  acordada para la extracción; los puertos ayudan a auditar, no deben introducir
  inadvertidamente una unidad distinta de la del artículo.
- Conserva el PCAP íntegro para extraer 0,5, 1 y 2 s con el mismo criterio de
  alineamiento y comparar después. Más duración no demuestra que 1 s sea óptimo.
- IP, puertos, tokens, semillas, nombres de fase y tiempos absolutos son metadatos
  de auditoría; no los añadas como predictores. Separa entrenamiento/evaluación
  por sesiones para evitar mezclar ventanas del mismo experimento.
- No prometas aceptación de los revisores ni inventes resultados. La aportación
  de este paquete es facilitar experimentos medibles y reproducibles.

## Control coordinado desde el PC de captura (14-10-2026)

El repositorio incluye `scripts_esp32/campaign/remote.py` para desplegar este
paquete por SSH en Arch y `capture_session.py` para coordinar inventario de
las cinco placas, servidor, TShark, actor, mediciones de reloj y descarga de
registros. Su guía está en `scripts_esp32/campaign/README.md`. Si se usa ese
controlador, no ejecutes otro actor manualmente. Para esta instalación el
servidor declarado es 10.37.225.138 y Arch es 10.37.225.230 (usuario jose);
son configuración del banco, no prueba de conectividad actual. No guardes
contraseñas en el repositorio ni en la ficha de sesión.
