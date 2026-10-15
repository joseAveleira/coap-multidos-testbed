# PCAP físico → CSV del artículo

Este extractor conserva las **23 variables y su orden** del dataset simulado
`coap-multidos-testbed` v1.0.0 (commit y hashes en `vendor/UPSTREAM.json`).
Se han copiado sin cambios las funciones originales de agregación y selección;
el adaptador añade lectura por lotes, varias duraciones y etiquetas auditables.
No entrena ni evalúa modelos.

Desde la raíz del repositorio, con Python 3.13 y TShark en PATH:

```powershell
python -m pip install -r scripts_esp32/dataset/requirements.txt
python scripts_esp32/dataset/extract.py --manifest recursos/dataset_fisico/pilotos_manifest.json --output .local/pilotos_reconstruidos
```

El destino debe ser nuevo. El manifiesto de entrada contiene rutas relativas a
su propia carpeta. `recursos/dataset_fisico/pilotos/` contiene la conversión ya
verificada de los dos pilotos físicos benignos guardados.

## Salidas y significado de una observación

Se generan `0_5s/`, `1_0s/` y `2_0s/`. Cada una contiene:

- `dataset_clean_multiclass.csv`: `meta_session`, 23 predictores y `target`.
- `dataset_complete_tracking.csv`: 60 columnas con metadatos y auditoría.
- `excluded_windows.csv`: ventanas descartadas y motivo.

Las observaciones son ventanas **activas de un par IPv4 bidireccional**, no un
total global del banco ni un flujo separado por puerto. Se alinean al origen
temporal del PCAP, no a la primera petición de cada cliente. No se inventan
ventanas vacías. Las tasas se dividen por 0,5/1/2 s según corresponda. La política
de fin excluye la ventana que termina después del último paquete CoAP observado;
se respetan además los límites START/STOP cuando el manifiesto los especifica.

`packet_extract/` conserva campos TShark, diagnósticos y, para campañas, la base
de correlación SQLite. `build_manifest.json` guarda versiones, hashes, conteos
por sesión/clase y motivos de exclusión. No es necesario cargar todo el PCAP en
memoria. `--chunksize` controla el lote orientativo; nunca se corta una ventana
de 2 s. Se rechazan timestamps que retroceden y campos CoAP incompletos.

## Etiquetas

`target`: **0 benigno, 1 Block2, 2 request flood**. Los IP/MAC, puertos, tiempos
absolutos, semillas y nombres de episodios se conservan como auditoría y no se
añaden a los 23 predictores.

Los clientes físicos declarados siguen siendo benignos durante los ataques.
Un participante desconocido se excluye. Sin actor se exige la declaración
explícita `traffic_declaration: "benign_only"` y la identidad de los clientes.

Con actor, se exigen sus seis archivos originales y sus hashes, ejecución
completada sin pérdidas del registro y una medición del desfase de relojes.
Se correlacionan envíos aceptados por UDP con los paquetes capturados mediante
puerto, MID y token; las respuestas NON se correlacionan por token porque pueden
tener otro MID. Cada respuesta conserva el episodio de su petición. Una ventana
del actor solo se retiene si todos sus paquetes pertenecen a la misma fase y
su intervalo completo cabe dentro de ella descontando la incertidumbre del
reloj. Precomprobaciones, guardas, paquetes sin correlación y fronteras mixtas
quedan fuera. La tasa elevada por sí sola nunca determina la etiqueta.

El controlador [de campaña](../campaign/README.md) genera el manifiesto necesario.
Las mediciones de reloj antes/después suponen que el desfase permanece dentro
de su envolvente; los saltos de reloj detectados invalidan la sesión. El registro
conserva las muestras y la incertidumbre para revisar esa condición.

## Orden temporal y auditoría de una captura física

Npcap puede escribir algunos paquetes fuera del orden de sus timestamps. El
original se conserva íntegro. Antes de extraer una campaña se puede generar una
copia ordenada con `reordercap`, sin modificar ninguna marca temporal:

```powershell
python scripts_esp32/dataset/order_capture.py --capture test/capturas/SESION
python scripts_esp32/dataset/extract.py --manifest test/capturas/SESION/dataset_chronological_manifest.json --output recursos/dataset_fisico/SESION
python scripts_esp32/dataset/audit_capture.py --capture test/capturas/SESION --export recursos/dataset_fisico/SESION
```

El primer paso verifica que la copia conserva el multiconjunto de paquetes,
incluyendo cada byte, longitud, interfaz y timestamp original. Guarda hashes de
ambos PCAP y el número y magnitud de las inversiones temporales. El extractor
sigue rechazando entradas desordenadas; no las corrige silenciosamente.

La auditoría comprueba los hashes de la exportación y vuelve a correlacionar
paquetes y registros. Produce `acquisition_audit.json` y `phase_summary.csv`, con
tasas programadas y efectivas, peticiones/respuestas observadas en el servidor,
timeouts y tiempos de respuesta medidos en el actor. Estos contadores describen
la adquisición; no equivalen a una evaluación de clasificadores ni permiten
localizar por sí solos una pérdida en la capa Wi-Fi.

## Verificación

`client_coverage.py` comprueba la continuidad de los clientes físicos a partir
del manifiesto de campaña completada y los campos por paquete ya extraídos:

```powershell
python scripts_esp32/dataset/client_coverage.py --campaign test/capturas/fisica_5_40min_20261015/campaign_completed.json --exports recursos/dataset_fisico --output .local/cobertura_reconstruida
```

El destino debe ser nuevo. Registra primeras/últimas peticiones, huecos máximos,
cobertura por intervalos de 10 s y hashes de sus fuentes. Distingue intervalos
completos del último fragmento parcial. Es una comprobación de presencia, no
una nueva resolución del dataset ni una medición de pérdida en Wi-Fi.

```powershell
python scripts_esp32/tests/dataset_test.py
python scripts_esp32/tests/pipeline_integration.py
```

La primera compara numéricamente los 23 atributos con el extractor original,
incluidas las tres duraciones y lotes pequeños, y comprueba las etiquetas.
La segunda dura unos 35 s, requiere Npcap/TShark, crea un servidor temporal y
captura tráfico **localhost de prueba**. Sus archivos quedan en `.local/`, fuera
del corpus físico. El resumen está en `test/pipeline_integracion_validacion.json`.

La comparación de rendimiento entre resoluciones corresponde al trabajo de
modelos/experimentos. Estos CSV suministran las entradas comparables.
