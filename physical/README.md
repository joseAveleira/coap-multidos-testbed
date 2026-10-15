# Physical CoAP dataset

The main campaign contains **five ten-minute captures (50 minutes), 909,093 CoAP packets, 30 Block2 episodes and 30 request-flood episodes**. Four ESP32-S3 clients and one ESP32-C6 client generate legitimate traffic; the Windows server/capture host and Arch Linux actor are separate machines on the physical Wi-Fi network.

## Download the main campaign

[Download the three clean CSVs with instructions and SHA-256 hashes](recursos/dataset_fisico/coap_fisico_30_csv.zip). These files contain exactly the five main captures; the pilots are excluded from this package.

| Window | Clean CSV | Rows | Benign | Block2 | Request flood |
|---|---|---:|---:|---:|---:|
| 0_5s | [CSV](recursos/dataset_fisico/campana_30_csv/0_5s/dataset_clean_multiclass.csv) | 20,032 | 19,173 | 420 | 439 |
| 1_0s | [CSV](recursos/dataset_fisico/campana_30_csv/1_0s/dataset_clean_multiclass.csv) | 13,628 | 13,229 | 195 | 204 |
| 2_0s | [CSV](recursos/dataset_fisico/campana_30_csv/2_0s/dataset_clean_multiclass.csv) | 7,685 | 7,517 | 81 | 87 |

Each CSV has 23 numeric predictors, `meta_session` and `target` (0 benign, 1 Block2, 2 request flood). Session identifies the complete capture and is not a predictor. The three resolutions aggregate the same packets. Episode counts, packet counts and CSV row counts describe different units.

## Complete archive and previous versions

The [combined export](recursos/dataset_fisico/dataset_v3/) also retains the three earlier pilots: **eight acquisitions, 964,126 packets**. The attack pilot contributes one episode per type, so this complete archive has 31 per type; use the main-campaign package above for 30 per type. Earlier `dataset_v1/` and `dataset_v2/` exports and every original capture remain unchanged. The earlier combined CSV bytes are an exact prefix of `dataset_v3`.

Tag `v1.0.0` preserves the simulated dataset; `v1.1.0` preserves the first physical release; `v1.2.0` adds one main capture and the explicit five-capture exports. No new classifier results are claimed.

## Evidence and reconstruction

- [Main-campaign manifest](recursos/dataset_fisico/campana_30_manifest.json): five captures.
- [Complete manifest](recursos/dataset_fisico/sesiones_v3_manifest.json): eight acquisitions.
- [Session parameters](recursos/dataset_fisico/resumen_configuracion_30.csv) and [episode records](recursos/dataset_fisico/episodios_campana_30.csv).
- [Verified summary](recursos/dataset_fisico/resumen_verificado_v3.json) and [client coverage](recursos/dataset_fisico/cobertura_clientes_50min.json).
- [Acquisition documentation](recursos/dataset_fisico/README.md), [raw captures and logs](test/capturas/), and [reproduction code](scripts_esp32/).
- [FILES.json](FILES.json): file sizes and SHA-256 hashes. Run `python verify_release.py` from this directory to verify the download.

The server exposes `/sensor` and `/large` (32 KiB in 1-KiB Block2 responses). The four S3 clients use Arduino and the C6 uses MicroPython 1.29.0. Actor logs and packet correlation determine phase labels, with measured clock uncertainty. Board traffic stays benign; guard, preflight, mixed-boundary, unmatched and incomplete windows are excluded and recorded. Original packets and timestamps are preserved in chronological copies.

The attempted fourth capture that failed during preflight and the initial fifth attempt stopped by the clock precheck remain recorded and excluded. Their valid replacements are `04_retry1` and `05_retry1`. The fifth attempt was repeated using the original Python 3.13.5 runtime without changing the clock guards.

With Python 3.13, the dependencies in `scripts_esp32/dataset/requirements.txt`, and TShark 4.6.4, run from `physical/`:

```powershell
python scripts_esp32/dataset/extract.py --manifest recursos/dataset_fisico/campana_30_manifest.json --output rebuilt_main
```

Use `sesiones_v3_manifest.json` for the complete collection and a new output directory. The 23 feature definitions and target codes are unchanged from the simulated dataset. See [CITATION.cff](../CITATION.cff) for citation; data/documentation use CC BY 4.0 and code uses MIT.
