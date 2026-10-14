# Alternate software environment replay

descriptive comparison of declared requests, exact scheduled trials and recorded environment/build evidence.

| Base run | Alternate run | Same admission | Complete alternate ready cases | Alternate trials |
|---|---|---|---:|---|
| all-lossless-explicit-runtime-final-20261013 | all-lossless-alternate-20261013 | True | 119/119 | {'ok': 833} |
| bounded-quality-final-20261013 | bounded-quality-alternate-20261013 | True | 9/9 | {'ok': 63} |
| empirical-quality-final-20261013 | empirical-quality-alternate-20261013 | True | 4/4 | {'ok': 28} |

each run retains its declared sessions and rounds; randomized assignment across environments and physical host identity are not established by this analysis; timing is descriptive.
Per-case scheduled denominators, missing trial keys, all statuses, successful primary-trial sizes/quality/times and raw-line traces are in summary.json. Partial metrics are explicitly conditional on success.
