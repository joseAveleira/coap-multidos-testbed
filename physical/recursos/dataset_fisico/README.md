# Dataset físico CoAP: 30 episodios de cada ataque

La campaña principal reúne **cinco capturas de diez minutos (50 minutos)**,
**30 episodios Block2 y 30 request flood**, con cuatro ESP32-S3 y una ESP32-C6
generando tráfico legítimo. Servidor y captura Windows, actor Arch y clientes
se comunican por Wi-Fi física. Se mantienen los 23 predictores y las etiquetas.

## CSV para trabajar con los 30 episodios por tipo

- [ZIP de CSV limpios](coap_fisico_30_csv.zip): tres resoluciones, LEEME y hashes.
- [Tablas de la campaña](campana_30_csv/): cinco capturas, sin los pilotos.
- [Manifiesto de las cinco capturas](campana_30_manifest.json).

| Resolución | Filas | Benigno | Block2 | Request flood |
|---|---:|---:|---:|---:|
| 0_5s | 20032 | 19173 | 420 | 439 |
| 1_0s | 13628 | 13229 | 195 | 204 |
| 2_0s | 7685 | 7517 | 81 | 87 |

Cada tabla limpia tiene 25 columnas: `meta_session`, 23 predictores y `target`.
El identificador representa la captura completa; cada captura incluye seis
episodios de cada ataque. Un episodio no equivale a una fila del CSV. Las tres
resoluciones agregan los mismos paquetes. Se conservan también las tablas de
auditoría de 60 columnas y las ventanas excluidas con su motivo.

## Ampliación y conservación de los datos anteriores

Se añadió `fisica_5_20261015_05_retry1` con 195063 paquetes
CoAP y seis episodios de cada ataque. Las cuatro capturas anteriores permanecen
intactas. El total principal es **909093 paquetes**.

`dataset_v3/` combina las cinco capturas principales y los tres pilotos:
**ocho adquisiciones, 964126 paquetes**. El piloto con actor
añade un episodio de cada tipo; por eso esta colección completa contiene 31
por tipo, mientras `campana_30_csv/` contiene exactamente la campaña de 30.
Los CSV de `dataset_v2/` son un prefijo idéntico byte a byte de los de `dataset_v3/`.
`dataset_v1/`, `dataset_v2/`, sus manifiestos y sus capturas se conservan.

| Captura | Paquetes CoAP | Filas 0,5 s | Filas 1 s | Filas 2 s |
|---|---:|---:|---:|---:|
| piloto_esp32_20261013_01 | 380 | 189 | 164 | 82 |
| piloto_banco4_20261014_01 | 2520 | 904 | 803 | 525 |
| fisica_4_actor_piloto_20261014_03 | 52133 | 1115 | 784 | 460 |
| fisica_5_20261015_01 | 199675 | 3967 | 2712 | 1528 |
| fisica_5_20261015_02 | 182403 | 4027 | 2747 | 1539 |
| fisica_5_20261015_03 | 166427 | 3967 | 2707 | 1541 |
| fisica_5_20261015_04_retry1 | 165525 | 4080 | 2767 | 1553 |
| fisica_5_20261015_05_retry1 | 195063 | 3991 | 2695 | 1524 |

## Evidencia

- `test/capturas/fisica_5_40min_20261015/`: cuatro capturas previas.
- `test/capturas/fisica_5_ampliacion_30_20261015/`: captura adicional e intento previo.
- `sesiones_v3_manifest.json`: ocho adquisiciones y rutas relativas.
- `resumen_verificado_v3.json` y `verificacion_v3.json`: conteos e integridad.
- `resumen_configuracion_30.csv` y `episodios_campana_30.csv`: parámetros y episodios.
- `cobertura_clientes_50min.json` y `.csv`: presencia de las cinco placas.
- `campana_30_csv/build_manifest.json`: selección exacta por identificador de captura.
- `test/ampliacion_30_20261015/`: red, reloj y conservación de la versión anterior.

Presencia de todos los clientes en cada intervalo completo de 10 s:
**True**; mayor intervalo
observado entre peticiones de una placa: **9.92 s**.
Estas medidas describen cobertura, no rendimiento de clasificadores.

El intento inicial de la quinta captura se detuvo en la comprobación del reloj,
antes de iniciar ataques. Usaba Python 3.12 con una resolución temporal más
gruesa que el umbral del controlador. La repetición con Python 3.13.5, igual que
en la campaña anterior, superó las comprobaciones sin desactivar ninguna guarda.
Ambos intentos quedan conservados; solo la repetición válida entra en los CSV.

Los registros de los cinco actores finalizaron sin pérdidas. Las etiquetas se
obtienen de los eventos externos y su correlación con paquetes, descontando
la incertidumbre medida entre relojes. El tráfico de las placas sigue siendo
benigno durante los ataques. Se conservan PCAP originales y copias cronológicas,
verificando los bytes y timestamps de cada paquete.

## Reproducción

Desde la raíz del repositorio, con Python 3.13, las dependencias del extractor
y TShark 4.6.4:

```powershell
python scripts_esp32/dataset/extract.py --manifest recursos/dataset_fisico/campana_30_manifest.json --output .local/campana_30_reconstruida
```

Para reconstruir la colección con pilotos, usar `sesiones_v3_manifest.json`.
El destino debe ser nuevo. [Definiciones y etiquetado](../../scripts_esp32/dataset/README.md).

La nueva versión de distribución pública es `v1.2.0` en
[coap-multidos-testbed](https://github.com/joseAveleira/coap-multidos-testbed).
`v1.0.0` conserva el dataset simulado y `v1.1.0` la primera ampliación física.
Los nombres `dataset_v1/v2/v3` son versiones de exportación internas, distintas
de las etiquetas del repositorio público. No se han entrenado modelos ni
modificado sus apartados de experimentos, resultados o conclusiones.
