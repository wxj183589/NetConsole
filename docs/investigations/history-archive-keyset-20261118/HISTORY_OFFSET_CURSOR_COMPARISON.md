# OFFSET and Cursor Comparison

## Method

Synthetic SQLite databases only; `site_id=demo`; no production or real development data was opened. Dataset sizes were 100,000, 500,000 and 1,000,000 rows. Each point used five iterations and page size 100. The benchmark compared equivalent logical rows and recorded SQL/connection counts.

## Results (P50 / P95, milliseconds)

| Rows | Page | OFFSET P50/P95 | Cursor P50/P95 | SQL each | Connections each | Same records |
| ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 100k | 1 | 37.052 / 39.755 | n/a (first page uses OFFSET-compatible mode) | 4 | 1 | yes |
| 100k | 10 | 44.665 / 45.447 | 57.077 / 57.911 | 4 | 1 | yes |
| 100k | 100 | 118.863 / 125.890 | 56.444 / 56.956 | 4 | 1 | yes |
| 100k | 500 | 1095.879 / 1123.787 | 57.555 / 67.185 | 4 | 1 | yes |
| 100k | 1000 | 1471.258 / 1477.151 | 75.946 / 76.946 | 4 | 1 | yes |
| 500k | 10 | 258.761 / 272.583 | 351.859 / 409.609 | 4 | 1 | yes |
| 500k | 100 | 443.432 / 446.867 | 397.124 / 429.440 | 4 | 1 | yes |
| 500k | 500 | 2071.325 / 2159.594 | 327.899 / 350.605 | 4 | 1 | yes |
| 500k | 1000 | 3586.578 / 4004.321 | 298.819 / 338.130 | 4 | 1 | yes |
| 500k | 2500 | 5586.148 / 5707.527 | 275.122 / 337.206 | 4 | 1 | yes |
| 1m | 10 | 398.192 / 416.011 | 623.059 / 660.897 | 4 | 1 | yes |
| 1m | 100 | 518.600 / 618.461 | 572.589 / 618.519 | 4 | 1 | yes |
| 1m | 500 | 2071.178 / 2107.038 | 599.064 / 660.576 | 4 | 1 | yes |
| 1m | 1000 | 3631.642 / 3709.666 | 560.247 / 639.330 | 4 | 1 | yes |
| 1m | 5000 | 11364.972 / 11421.435 | 524.274 / 619.276 | 4 | 1 | yes |

The benchmark's cursor predicate used the original four logical sort fields. The shipped implementation keeps those fields and adds `source_rowid` only to resolve exact ties, so it preserves the measured continuation behavior while making tie order deterministic.

## Interpretation

Cursor continuation has a small shallow-page overhead because the predicate is more complex. At deep offsets it avoids re-reading the prefix: the 1m-row page-5000 point falls from 11.365 s P50 to 0.524 s P50 (95.4% lower). Both modes still use one read connection and four SQL statements, including the existing count and grouped detail reads.

`TEMP B-TREE` remains in the union-level plan. Removing it would require a separate schema/index design and is outside this task.
