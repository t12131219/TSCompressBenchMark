# CPU length and quality study

Read-only reconstruction from raw trials. Nested lengths and repeated sessions do not create independent data sources.

Requested cases: 132; complete: 132.

| Method / zstd-frame baseline | Condition group | Metric | Pairs | Sources | Baseline / method | Exploratory 95% source interval |
|---|---|---|---:|---:|---:|---|
| elf-star | afce218af508 | encode_ns | 6/6 | 3 | 0.6488 | 0.6255–0.677 |
| elf-star | afce218af508 | decode_ns | 6/6 | 3 | 0.9916 | 0.9829–1.002 |
| elf-star | afce218af508 | stored_bytes | 6/6 | 3 | 1.045 | 0.877–1.212 |
| lzss-raw | b1ce78d6893d | encode_ns | 6/6 | 3 | 0.6041 | 0.562–0.6446 |
| lzss-raw | b1ce78d6893d | decode_ns | 6/6 | 3 | 1.005 | 0.9985–1.01 |
| lzss-raw | b1ce78d6893d | stored_bytes | 6/6 | 3 | 0.974 | 0.9369–1.012 |
| chimp128 | b859e42ce679 | encode_ns | 6/6 | 3 | 1.05 | 1.028–1.089 |
| chimp128 | b859e42ce679 | decode_ns | 6/6 | 3 | 1 | 0.9945–1.007 |
| chimp128 | b859e42ce679 | stored_bytes | 6/6 | 3 | 0.916 | 0.8663–0.9912 |
| alp-rd | c03dc9fb7583 | encode_ns | 6/6 | 3 | 1.126 | 1.121–1.132 |
| alp-rd | c03dc9fb7583 | decode_ns | 6/6 | 3 | 1.011 | 1.006–1.015 |
| alp-rd | c03dc9fb7583 | stored_bytes | 6/6 | 3 | 0.2803 | 0.2701–0.298 |
| lz4-frame | ddcb837120eb | encode_ns | 6/6 | 3 | 1.052 | 1.045–1.067 |
| lz4-frame | ddcb837120eb | decode_ns | 6/6 | 3 | 1.003 | 1.002–1.006 |
| lz4-frame | ddcb837120eb | stored_bytes | 6/6 | 3 | 0.8162 | 0.7847–0.8333 |
| raw-store | fb8f6d4dd15f | encode_ns | 6/6 | 3 | 2.499 | 2.429–2.551 |
| raw-store | fb8f6d4dd15f | decode_ns | 6/6 | 3 | 10.03 | 9.953–10.11 |
| raw-store | fb8f6d4dd15f | stored_bytes | 6/6 | 3 | 0.649 | 0.6352–0.6712 |

Intervals resample sources, equally weighted; they are conditional on these few selected sources. No p-values, multiplicity claims, or overall winner.
Quality and complete/payload/header values, all statuses and per-trial trace are in summary.json.
