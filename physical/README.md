# Physical CoAP dataset

This extension contains seven verified acquisitions with **769,063 CoAP packets**. Four main captures last 600 seconds each (40 minutes), with five physical clients and a separate server and attack actor. The earlier three pilots remain identified separately. No new classifier results are claimed in this release.

## Download the data

Clone this repository or download the archive for tag `v1.1.0`. Paths below are relative to `physical/`.

| Window | Clean CSV | Rows | Benign | Block2 | Request flood |
|---|---|---:|---:|---:|---:|
| 0.5 s | [CSV](recursos/dataset_fisico/dataset_v2/0_5s/dataset_clean_multiclass.csv) | 18,249 | 17,495 | 389 | 365 |
| 1 s | [CSV](recursos/dataset_fisico/dataset_v2/1_0s/dataset_clean_multiclass.csv) | 12,684 | 12,332 | 184 | 168 |
| 2 s | [CSV](recursos/dataset_fisico/dataset_v2/2_0s/dataset_clean_multiclass.csv) | 7,228 | 7,076 | 79 | 73 |

Each clean CSV contains 23 numeric predictors, `meta_session` and `target`. Target codes are 0 (benign), 1 (Block2 amplification), and 2 (request flood). Use `meta_session` for grouping; it is not a predictor. The accompanying 60-column tables preserve audit metadata. Windows at different resolutions are alternative aggregations of the same packets, not independent observations.

The four five-board sessions contain **24 episodes of each attack**, six per type per session. Their one-second tables contain 10,611 benign, 163 Block2 and 159 request-flood windows. The older attack pilot adds one episode of each type; it accounts for the different combined class totals above.

## Acquisition and labels

Four ESP32-S3 boards run Arduino clients; one ESP32-C6 runs MicroPython 1.29.0. All five generate legitimate requests. A Windows PC runs the CoAP server and TShark on its physical Wi-Fi interface; a separate Arch Linux PC generates scheduled attacks and benign workloads. The server provides `/sensor` and a 32-KiB `/large` resource in 1-KiB Block2 responses. All devices communicate through a 2.4-GHz Wi-Fi access point.

Raw captures are restricted to CoAP traffic at the server. Logged requests and responses identify actor phases, with measured clock uncertainty applied before labelling complete windows. Preflight, guard, mixed-boundary, unmatched and incomplete windows are excluded with reasons. Traffic from the five boards remains benign during attack phases.

## Files and provenance

- [Seven-session manifest](recursos/dataset_fisico/sesiones_v2_manifest.json): capture paths and observed endpoints.
- [Main-campaign manifest](recursos/dataset_fisico/campana_5_manifest.json): only the four five-board sessions.
- [Raw captures](test/capturas/): original PCAPNGs, chronological copies, actor/server logs and clock records.
- [Dataset tables](recursos/dataset_fisico/dataset_v2/): complete and clean CSVs, exclusions, packet fields and build hashes.
- [Session parameters](recursos/dataset_fisico/resumen_configuracion_5.csv): seeds, attack rates, duration ranges, message types, block orders and token policies.
- [Episode records](recursos/dataset_fisico/episodios_campana_5.csv): actual timing, achieved rates, requests/responses and timeouts.
- [Coverage audit](recursos/dataset_fisico/cobertura_clientes_40min.json): client presence in each complete 10-second interval.
- [Verified summary](recursos/dataset_fisico/resumen_verificado_v2.json): acquisition, class and ordering counts.
- [Extractor](scripts_esp32/dataset/), [actor](scripts_esp32/actor/), [server](scripts_esp32/servidor/) and [client sources](scripts_esp32/firmware/).
- [Recorded plans](test/planes/) and [C6 installation evidence](test/c6_micropython_20261015/).
- [FILES.json](FILES.json): SHA-256 and size of every copied evidence/source file.

The attempted fourth main acquisition that failed during preflight is preserved for provenance and excluded from every CSV; `04_retry1` is the valid replacement. Original bytes are retained, including recorded local paths and lab network identifiers. These document the acquisition host; the reconstruction manifests use relative paths.

## Verify the download

From `physical/`, run `python verify_release.py`. This checks all published evidence hashes, seven capture paths, and class counts and finite predictors at every resolution.

## Reconstruct the CSVs

Use Python 3.13 and TShark 4.6.4 (or verify compatibility before changing versions). From `physical/`:

```powershell
python -m pip install -r scripts_esp32/dataset/requirements.txt
python scripts_esp32/dataset/extract.py --manifest recursos/dataset_fisico/sesiones_v2_manifest.json --output rebuilt
```

The output directory must not already exist. Use `campana_5_manifest.json` to rebuild only the main campaign. The original aggregation and feature-selection functions are vendored from `v1.0.0`; the adapter supplies physical capture fields and external phase labels. The published `.sqlite` and packet-field files are intermediate audit products, not extra training observations.

## Versions and citation

`v1.0.0` identifies the unchanged simulated collection. `v1.1.0` adds this physical supplement; the folder name `dataset_v2` refers to the internal export that combines three pilots and four main sessions. They are different version namespaces. Use the repository tag and [CITATION.cff](../CITATION.cff) when citing this release. Data/documentation use CC BY 4.0 and code uses MIT, as in the original release.
