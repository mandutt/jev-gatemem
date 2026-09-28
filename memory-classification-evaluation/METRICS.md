# METRICS.md

## Summary (n=1500)

- MemoryType exact-match accuracy: **0.057**
- should_store precision: 0.287 (430/1500)
- should_store recall: 1.000 (430/430)
- should_store F1: 0.446
- unknown rate: 0.000

## Per-type metrics

| type | n_gold | precision | recall | F1 |
|---|---|---|---|---|
| fact | 118 | 0.208 | 0.542 | 0.300 |
| preference | 149 | 0.000 | 0.000 | 0.000 |
| decision | 10 | 0.000 | 0.000 | 0.000 |
| commitment | 24 | 0.000 | 0.000 | 0.000 |
| goal | 16 | 0.000 | 0.000 | 0.000 |
| event | 58 | 0.000 | 0.000 | 0.000 |
| instruction | 10 | 0.000 | 0.000 | 0.000 |
| relationship | 10 | 0.000 | 0.000 | 0.000 |
| context | 26 | 0.018 | 0.808 | 0.034 |
| learning | 3 | 0.000 | 0.000 | 0.000 |
| observation | 4 | 0.000 | 0.000 | 0.000 |
| error | 2 | 0.000 | 0.000 | 0.000 |
| NO_STORE | 1070 | 0.000 | 0.000 | 0.000 |

## Confusion pairs (지시문 §13)

| gold → pred | count |
|---|---|
| fact → context | 54 |
| event → context | 47 |

## Top confusions (전체)

| gold → pred | count |
|---|---|
| NO_STORE → context | 878 |
| NO_STORE → fact | 192 |
| preference → context | 134 |
| fact → context | 54 |
| event → context | 47 |
| commitment → context | 16 |
| preference → fact | 15 |
| goal → context | 13 |
| event → fact | 11 |
| relationship → context | 10 |
| commitment → fact | 8 |
| decision → context | 6 |
| instruction → context | 6 |