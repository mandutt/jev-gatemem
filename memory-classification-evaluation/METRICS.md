# METRICS.md

## Summary (n=390)

- MemoryType exact-match accuracy: **0.051**
- should_store precision: 0.377 (147/390)
- should_store recall: 1.000 (147/147)
- should_store F1: 0.547
- unknown rate: 0.000

## Per-type metrics

| type | n_gold | precision | recall | F1 |
|---|---|---|---|---|
| fact | 24 | 0.241 | 0.583 | 0.341 |
| preference | 45 | 0.000 | 0.000 | 0.000 |
| decision | 6 | 0.000 | 0.000 | 0.000 |
| commitment | 12 | 0.000 | 0.000 | 0.000 |
| goal | 4 | 0.000 | 0.000 | 0.000 |
| event | 26 | 0.000 | 0.000 | 0.000 |
| instruction | 9 | 0.000 | 0.000 | 0.000 |
| relationship | 7 | 0.000 | 0.000 | 0.000 |
| context | 8 | 0.018 | 0.750 | 0.035 |
| learning | 4 | 0.000 | 0.000 | 0.000 |
| observation | 2 | 0.000 | 0.000 | 0.000 |
| NO_STORE | 243 | 0.000 | 0.000 | 0.000 |

## Confusion pairs (지시문 §13)

| gold → pred | count |
|---|---|
| fact → context | 10 |
| event → context | 20 |

## Top confusions (전체)

| gold → pred | count |
|---|---|
| NO_STORE → context | 216 |
| preference → context | 43 |
| NO_STORE → fact | 27 |
| event → context | 20 |
| fact → context | 10 |
| commitment → context | 9 |
| instruction → context | 8 |
| relationship → context | 7 |
| event → fact | 6 |
| decision → context | 5 |
| goal → context | 4 |
| commitment → fact | 3 |
| learning → context | 3 |