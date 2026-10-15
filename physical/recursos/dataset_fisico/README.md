# Dataset físico CoAP: siete adquisiciones verificadas

`dataset_v2/` reúne **769063 paquetes CoAP** de siete
adquisiciones, con los mismos 23 predictores del dataset simulado. La campaña
del 15-10-2026 aporta cuatro capturas principales de 600 s (**40 minutos**),
714030 paquetes, cuatro ESP32-S3, una ESP32-C6 y el actor Arch.
Se ejecutaron **24 episodios Block2 y 24 request flood** en esta nueva campaña;
el piloto previo aporta además un episodio de cada tipo. Las cinco placas son
clientes legítimos durante toda la campaña.

El servidor y TShark están en Windows (`10.37.225.138`); el actor está en un PC
Arch separado (`10.37.225.230`). Todos se comunican por Aveleira, 2,4 GHz.
Las S3 utilizan Arduino y la C6 utiliza MicroPython 1.29.0 con el cliente CoAP
05. La ficha de cada captura contiene las MAC/IP observadas y los hashes del
cliente C6; su instalación y consola están en `test/c6_micropython_20261015/`.

| Sesión | Placas | Paquetes CoAP | Ventanas 0,5 s | Ventanas 1 s | Ventanas 2 s |
|---|---:|---:|---:|---:|---:|
| piloto_esp32_20261013_01 | 1 | 380 | 189 | 164 | 82 |
| piloto_banco4_20261014_01 | 4 | 2520 | 904 | 803 | 525 |
| fisica_4_actor_piloto_20261014_03 | 4 | 52133 | 1115 | 784 | 460 |
| fisica_5_20261015_01 | 5 | 199675 | 3967 | 2712 | 1528 |
| fisica_5_20261015_02 | 5 | 182403 | 4027 | 2747 | 1539 |
| fisica_5_20261015_03 | 5 | 166427 | 3967 | 2707 | 1541 |
| fisica_5_20261015_04_retry1 | 5 | 165525 | 4080 | 2767 | 1553 |
| Total | | **769063** | **18249** | **12684** | **7228** |

| Resolución | Benigno (0) | Block2 (1) | Request flood (2) |
|---|---:|---:|---:|
| 0,5 s | 17495 | 389 | 365 |
| 1 s | 12332 | 184 | 168 |
| 2 s | 7076 | 79 | 73 |

Las filas son ventanas activas por par IPv4 bidireccional. Los 60 s de inventario
anteriores a cada captura principal están conservados por separado y no forman
parte del CSV. Cada plan del actor dura 565 s; los 600 s de captura incluyen
precomprobación y márgenes. Las mediciones de reloj y las transferencias de los
registros también prolongan el tiempo de operación, sin añadir sesiones al corpus.

## Evidencia y reproducción de la versión ampliada

- `sesiones_v2_manifest.json`: las siete fuentes del conjunto ampliado.
- `campana_5_manifest.json`: solo las cuatro sesiones con cinco placas.
- `dataset_v2/`: CSV limpios de 25 columnas (23 predictores, sesión y clase),
  tablas de auditoría de 60 columnas, exclusiones, campos por paquete y hashes.
- `fisica_5_20261015_01/`, `02/`, `03/` y `04_retry1/` (mismo prefijo): exportaciones individuales,
  `acquisition_audit.json` y `phase_summary.csv` por sesión.
- `resumen_configuracion_5.csv`: semillas, tasas, duraciones reales, tipos de
  mensaje, orden de bloques y políticas de token por sesión.
- `episodios_campana_5.csv`: tiempos de inicio/fin, tasas objetivo/efectivas,
  envíos, paquetes observados, respuestas y timeouts por episodio.
- `resumen_sesiones_v2.csv` y `resumen_verificado_v2.json`: recuentos comprobados.
- `cobertura_clientes_40min.csv` y `.json`: presencia de cada placa durante
  cada sesión, tiempos extremos y mayor intervalo entre peticiones.
- `test/capturas/fisica_5_40min_20261015/`: PCAP originales, copias cronológicas,
  inventarios, planes, actor, servidor y mediciones de reloj.

```powershell
python scripts_esp32/dataset/extract.py --manifest recursos/dataset_fisico/sesiones_v2_manifest.json --output .local/dataset_v2_reconstruido
```

El destino debe ser nuevo. Para reconstruir solo la campaña de cinco placas,
usar `campana_5_manifest.json` con otro destino. La ordenación preservó los bytes
y timestamps originales mediante comprobación del multiconjunto de paquetes.
Los actores terminaron sin pérdidas de registros. El etiquetado correlaciona
peticiones y respuestas con sus fases y aplica el margen de incertidumbre de
reloj; no clasifica como ataque el tráfico legítimo de las placas.

La ejecución conjunta está en `campaign_completed.json`. Conserva las tres
primeras sesiones y la repetición de la cuarta. El intento `fisica_5_20261015_04`
falló por timeout en la comprobación previa, antes de empezar ataques; queda
guardado como fallido y fuera de todos los CSV. `campaign_execution.json`
conserva el estado original de esa interrupción.

Las tres resoluciones permiten comparar la agregación del mismo tráfico.
No se entrenaron modelos ni se modificaron los experimentos del artículo.

Las cinco placas aparecen en todos los intervalos completos de 10 s de cada
sesión. El mayor intervalo entre peticiones de una misma placa es 5,07 s.
Estos intervalos solo comprueban cobertura, no sustituyen las ventanas de
variables. El informe también conserva el último intervalo parcial: en una
sesión dura solo unos 17 ms y no contiene tráfico de todas las placas.

```powershell
python scripts_esp32/dataset/client_coverage.py --campaign test/capturas/fisica_5_40min_20261015/campaign_completed.json --exports recursos/dataset_fisico --output .local/cobertura_reconstruida
```

## Versión anterior conservada: tres pilotos

`dataset_v1/` contiene tres adquisiciones físicas, **55033 paquetes CoAP** y los
mismos 23 predictores del dataset simulado. La tercera captura incluye los dos
ataques ejecutados desde Arch y tráfico legítimo de cuatro ESP32-S3. Los PCAP
se tomaron en la interfaz Wi-Fi física del servidor Windows, en Aveleira.

| Sesión | Clientes físicos | Captura asignada | Paquetes CoAP | Ventanas 0,5 s | Ventanas 1 s | Ventanas 2 s |
|---|---:|---:|---:|---:|---:|---:|
| piloto_esp32_20261013_01 | 1 S3 | 180 s | 380 | 189 | 164 | 82 |
| piloto_banco4_20261014_01 | 4 S3 | 300 s | 2520 | 904 | 803 | 525 |
| fisica_4_actor_piloto_20261014_03 | 4 S3 + actor Arch | 215 s | 52133 | 1115 | 784 | 460 |
| Total | | 695 s | **55033** | **2208** | **1751** | **1067** |

Las duraciones son las asignadas al capturador. El plan del actor dura 180 s;
su precomprobación, espera inicial y cierre caben dentro de los 215 s de captura.
Las dos primeras adquisiciones tienen límites START/STOP adicionales registrados
en el manifiesto. Las filas son ventanas activas por par IPv4 bidireccional,
por lo que varios clientes pueden aportar una observación en el mismo intervalo.

| Resolución | Benigno (0) | Block2 (1) | Request flood (2) |
|---|---:|---:|---:|
| 0,5 s | 2146 | 42 | 20 |
| 1 s | 1721 | 21 | 9 |
| 2 s | 1053 | 10 | 4 |

## Ataques ejecutados y trazabilidad

El actor está desplegado en `jose@10.37.225.230`, con Node.js 26.10.0. Los ataques
se dirigen al servidor `10.37.225.138:5683`; las placas siguen siendo benignas.
El episodio Block2 duró 22,21 s y el request flood 10,73 s. Sus objetivos fueron
100/500 peticiones por segundo y sus tasas efectivas de envío 100,03/496,99.
El servidor capturó 2221/5334 peticiones, respectivamente. También se ejecutaron
ráfagas benignas y descargas completas desde el mismo actor.

`fisica_4_actor_piloto_20261014_03/acquisition_audit.json` y `phase_summary.csv`
contienen contadores, tiempos, tasas, respuestas y timeouts por fase. El actor
terminó sin pérdidas de registros. La corrección de reloj medida fue -72,85 ms
(actor menos capturador), con una incertidumbre de 155,41 ms. Las etiquetas se
obtienen de sus registros y de la correlación de solicitudes, no de umbrales de
tráfico. Los CSV excluyen fronteras, guardas, precomprobaciones y orígenes desconocidos.

El PCAP original del actor tiene 36 inversiones de orden temporal de hasta
2,35 ms. Se conserva íntegro junto a una copia ordenada por `reordercap`.
La comprobación del multiconjunto verifica que todos los bytes y timestamps de
los 52133 paquetes se mantienen. La ordenación no ajusta los tiempos medidos.

## Archivos y reproducción

- `sesiones_manifest.json`: las tres adquisiciones y sus fuentes.
- `dataset_v1/`: exportación conjunta, CSV limpios de 25 columnas, tablas de
  auditoría de 60 columnas, exclusiones, campos por paquete y hashes.
- `pilotos/` y `pilotos_manifest.json`: los dos pilotos benignos previos.
- `fisica_4_actor_piloto_20261014_03/`: exportación y auditoría individual del
  piloto con ataques físicos.
- `test/capturas/`: PCAP, inventarios, registros originales y ejecuciones.
  Los intentos marcados `failed` no forman parte del dataset.

```powershell
python scripts_esp32/dataset/extract.py --manifest recursos/dataset_fisico/sesiones_manifest.json --output .local/dataset_fisico_reconstruido
```

El destino debe ser nuevo. Definiciones y controles:
[extractor](../../scripts_esp32/dataset/README.md),
[campaña](../../scripts_esp32/campaign/README.md) y
[guía de la IA del actor](../../scripts_esp32/actor/LEEME_IA.md).

