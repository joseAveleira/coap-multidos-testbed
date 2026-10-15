# CoAP multi-DoS datasets and testbeds

This repository distributes the original simulated CoAP campaign and a physical Wi-Fi extension. Tag `v1.0.0` preserves the original data and code; `v1.1.0` preserves the first physical release. Tag `v1.2.0` expands the main physical campaign to **30 episodes of each attack**.

| Collection | Location | Captures | CoAP packets | One-second rows |
|---|---|---:|---:|---:|
| Original simulated campaign | [data/](data/) | 15 | 624,058 | 3,797 |
| Main physical campaign | [CSV package](physical/recursos/dataset_fisico/coap_fisico_30_csv.zip) | 5 | 909,093 | 13,628 |
| Physical archive including pilots | [physical/](physical/) | 8 | 964,126 | 15,379 |

Five ESP32 clients, a Windows server/capture host and a separate Arch Linux actor communicate over physical Wi-Fi. The five main captures contain 30 Block2 and 30 request-flood episodes. The archive also preserves three identified pilots.

See [physical/README.md](physical/README.md) for the raw PCAPs, CSV resolutions, labels, schedules and checksums. The sections below describe the original simulated collection.

## Contents

- `testbed/`: Node.js CoAP server, clients and session orchestrator.
- `pipeline/`: TShark extraction and one-second conversation windows.
- `preprocessing/`: clean-table construction and validation.
- `data/`: complete and model-ready CSV files.
- `data/example/`: one small PCAPNG capture with its event log and summary.
- `manifests/`: seeds, versions and SHA-256 hashes from the 15-session campaign.

## Dataset

| Class | Windows |
|---|---:|
| Benign | 3,436 |
| Block2 amplification flood | 253 |
| Request flood | 108 |
| **Total** | **3,797** |

Each row represents one active bidirectional CoAP conversation in a non-overlapping one-second window. The complete table contains 60 fields. The clean table contains 23 numeric predictors, `meta_session` and `target`.

`meta_session` is used only to keep complete sessions together during evaluation. It must not be used as a predictor.

## Requirements

- Windows 10 or 11.
- Node.js 24 or compatible. No npm packages are required.
- Python 3.11 or compatible.
- Wireshark/TShark with Npcap and the `NPF_Loopback` adapter.

Install the Python packages:

```powershell
python -m pip install -r requirements.txt
```

## Check the published data

```powershell
python preprocessing\validate_artifacts.py
```

This verifies the table dimensions, class counts, session groups, retained predictors and the example capture.

## Run a short session

Open a terminal with permission to capture from Npcap loopback and run:

```powershell
python testbed\orchestrate.py --profile smoke --sessions 1 --overwrite
```

The smoke profile lasts approximately eight seconds and generates one Block2 episode. Outputs are written under `testbed/captures`, `testbed/events`, `testbed/metrics` and `testbed/logs`.

## Reproduce the complete campaign

```powershell
python testbed\orchestrate.py --profile strong --sessions 15 --overwrite
python pipeline\build_dataset.py --manifest testbed\session_manifest_strong.csv
python preprocessing\build_clean_dataset.py --input data\rebuilt\dataset_complete_tracking.csv --output data\rebuilt\dataset_clean_multiclass.csv
```

Each strong session lasts approximately 68 seconds and contains five Block2 episodes and two request-flood episodes. Benign sensor bursts and legitimate Block2 transfers remain active during the sessions.

The raw 15-session PCAP collection is not committed because of its size. It can be regenerated with the command above. The reference manifest in `manifests/` records the original seeds and capture hashes.

## Ground truth

Attack intervals are written by the orchestrator to JSONL files. Labels are assigned after capture. A window receives an attack label only when the endpoint pair matches the recorded event and the complete window is contained in the event interval. The 190 partially overlapping boundary windows are provided separately and are not included in the modelling table.

## Evaluation

Use leave-one-session-out or another group-wise split based on `meta_session`. Fit scaling, feature transformation and resampling only on the training sessions of each fold.

## Scope

The original collection uses a controlled loopback testbed. The physical extension records CoAP on a Wi-Fi network with separate microcontrollers, server and actor. The collections remain separately identifiable; this release supplies acquisition data and makes no new classifier-performance claims.

## Citation

Citation metadata are provided in [`CITATION.cff`](CITATION.cff). The paper reference can be updated when the journal version receives its final bibliographic information.

## Licences

Code is released under the MIT License. Data and documentation are released under CC BY 4.0. See [`LICENSE`](LICENSE) and [`LICENSE-DATA.md`](LICENSE-DATA.md).
