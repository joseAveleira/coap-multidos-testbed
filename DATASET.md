# Dataset notes

## Observation unit

An observation is the bidirectional CoAP traffic of one unordered endpoint pair during one non-overlapping one-second interval. Packet order, message direction and timing are used to calculate aggregate features.

## Files

- `dataset_complete_tracking.csv`: 3,797 rows and 60 fields. It retains metadata and auxiliary labels for audit.
- `dataset_clean_multiclass.csv`: 3,797 rows, 23 predictors, `meta_session` and `target`.
- `data_dictionary.csv`: field type, role, clean-table status and description.
- `feature_cleaning_audit.csv`: retained and removed features with the selection reason.
- `attack_intervals.csv`: external attack-event records.
- `excluded_boundary_windows.csv`: 190 partial-overlap windows excluded from modelling.
- `quality_checks.csv`: dataset-level validation checks.

## Target mapping

| Target | Meaning |
|---:|---|
| 0 | Benign traffic |
| 1 | Block2 amplification flood |
| 2 | Request flood |

For binary detection, merge targets 1 and 2 into a single attack class.

## Predictor groups

The 23 predictors describe:

- traffic volume and frame length;
- inter-arrival time and active span;
- CoAP request, response and message-type behaviour;
- payload lengths and response/request ratios;
- Block2 request, response, sequence and token behaviour.

Payload-related fields contain only aggregate lengths or byte counts. Message content, IP addresses, capture identifiers and auxiliary labels are not included in the clean predictor set.

## Cleaning

The source table has no missing or infinite values. Cleaning removed constant fields, metadata, identifiers, auxiliary ground truth, nine exact duplicate or deterministic transformations and one near-constant response field. No rows were removed or imputed.

## Split rule

Always split by `meta_session`. Random row-level splitting can place adjacent windows from one generated session in both training and test data.
