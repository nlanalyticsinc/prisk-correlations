# PRisk Reproduction Correlations

This repository checks whether separately downloaded NLA CSVs faithfully reproduce the paper-based `PRisk`, `PSentiment`, and topic-specific `PRiskT` measures from Hassan, Hollander, van Lent, and Tahoun's article ["Firm-Level Political Risk: Measurement and Effects"](https://doi.org/10.1093/qje/qjz021) in *The Quarterly Journal of Economics* (2019).

The main evidence is a set of Pearson correlations between the original paper-based firm-quarter measures and the reproduced NLA measures. The correlations are written at the firm-quarter level and at a quarterly-mean level so the closeness of the reproduced series can be inspected directly.

## Headline Results

These correlations were generated from NLA files downloaded on June 24, 2026 with version `v2.1`. The CSV outputs keep full numeric precision.

| Series | Firm-quarter Pearson | Quarter Pearson | Matched firm-quarters | Quarters |
|---|---:|---:|---:|---:|
| `PRisk` | 0.91 | 0.98 | 310,303 | 81 |
| `PSentiment` | 0.86 | 0.95 | 310,303 | 81 |
| `PRiskT_economic` | 0.91 | 0.99 | 310,303 | 81 |
| `PRiskT_environment` | 0.86 | 0.98 | 310,303 | 81 |
| `PRiskT_trade` | 0.81 | 0.95 | 310,303 | 81 |
| `PRiskT_institutions` | 0.89 | 0.99 | 310,303 | 81 |
| `PRiskT_health` | 0.85 | 0.98 | 310,303 | 81 |
| `PRiskT_security` | 0.82 | 0.97 | 310,303 | 81 |
| `PRiskT_tax` | 0.90 | 0.99 | 310,303 | 81 |
| `PRiskT_technology` | 0.87 | 0.99 | 310,303 | 81 |
| Average | 0.87 | 0.98 | - | - |

## Data

Data files are downloaded separately and are not tracked in git.

- Original paper-based CSV: download from [`firmlevelrisk.com`](https://firmlevelrisk.com/) and place one `firmquarter_*.csv` or `firmlevel_*.csv` file in `data/original/`.
- Reproduced NLA CSVs: download the political-risk CSV files from [`apps.nlanalytics.tech/curated-measures/political-risk/`](https://apps.nlanalytics.tech/curated-measures/political-risk/) and place the `NLA_*_firmlevel.csv` files in one reproduced-data directory.

The original CSV is read as tab-delimited and must contain `gvkey`, `date`, and the original score columns listed below. It is expected to contain at most one row per `gvkey`-`date`; duplicate original firm-quarter rows are treated as an error. Each NLA CSV must contain `gvkey`, `start_time`, `nr_of_words`, and the relevant raw numerator column, either `risk` or `sentiment`.

Expected local layout:

```text
data/
  original/
    firmquarter_2022q1.csv
  reproduced/
    NLA_*_firmlevel.csv
```

The script defaults to `data/reproduced/`. To use a different reproduced-data directory, either change `REPRODUCED_DIR` near the top of `scripts/correlate_original_reproduced.py` or pass `--reproduced-dir`.

## What Is Compared

The script compares these original columns against the matching reproduced NLA files:

| Original column | NLA filename fragment | Reproduced value |
|---|---|---|
| `PRisk` | `prisk-and-psentiment` | `risk / nr_of_words` |
| `PSentiment` | `prisk-and-psentiment` | `sentiment / nr_of_words` |
| `PRiskT_economic` | `topic-based-prisk-economy` | `risk / nr_of_words` |
| `PRiskT_environment` | `topic-based-prisk-environment` | `risk / nr_of_words` |
| `PRiskT_trade` | `topic-based-prisk-trade` | `risk / nr_of_words` |
| `PRiskT_institutions` | `topic-based-prisk-institutions` | `risk / nr_of_words` |
| `PRiskT_health` | `topic-based-prisk-health` | `risk / nr_of_words` |
| `PRiskT_security` | `topic-based-prisk-security` | `risk / nr_of_words` |
| `PRiskT_tax` | `topic-based-prisk-tax` | `risk / nr_of_words` |
| `PRiskT_technology` | `topic-based-prisk-technology` | `risk / nr_of_words` |

The script expects at most one matching NLA file per measure and reports any unavailable series.

The aggregation is intentionally asymmetric because the two inputs have different granularity. The original paper-based CSV is already at firm-quarter level, so each `gvkey`-`date` row is used directly. The reproduced NLA files are call-level files, so multiple NLA rows can fall in the same firm-quarter. Those rows are converted from `start_time` to `dateQ`, grouped by `gvkey` and `dateQ`, then aggregated by summing the numerator and `nr_of_words` before dividing. This computes `sum(risk) / sum(nr_of_words)` or `sum(sentiment) / sum(nr_of_words)`, rather than an unweighted average of call-level ratios. Correlations are computed only on matched `gvkey`-`dateQ` observations.

## Run

The command-line script uses only the Python standard library:

```sh
python3 scripts/correlate_original_reproduced.py
```

With all expected NLA files present, the full run is roughly a 40-45 second job on the current local machine; the latest local validation run completed in 42.5 seconds. Most of that time is spent reading and aggregating the reproduced firm-level CSVs.

Override the reproduced-data directory explicitly:

```sh
python3 scripts/correlate_original_reproduced.py --reproduced-dir data/reproduced
```

The script writes outputs to `data/correlations/`.

## Outputs

The main generated files are:

- `data/correlations/firm_quarter_correlations.csv`
- `data/correlations/quarterly_mean_correlations.csv`

Use the `pearson` column as the main validation statistic. Values close to 1, together with large matched sample sizes, are the evidence that the NLA series closely track the original paper-based measures. The `gvkey-dateQ` output is the stricter firm-quarter comparison; the `dateQ` output compares quarterly means after matching firm-quarter observations. The `n_pairs`, `n_dateQ`, and `matched_gvkey_dateQ` columns show the matched sample size behind each correlation.

## Notebook

`reproduced_final_correlations.ipynb` is a thin wrapper around the same script. Use it if you want to rerun the correlations and inspect the output tables interactively.

The notebook dependencies are optional:

```sh
python3 -m venv venv
venv/bin/python -m pip install -e ".[notebook]"
```

## Limitations

This repository checks correlation and coverage, not byte-for-byte equality. Very high correlations indicate that the reproduced NLA series are close to the original paper-based measures over the matched sample, but any skipped series, missing observations, or changes in downloaded source files should be checked through the output filenames and sample-size columns.

## License

Code in this repository is licensed under the MIT License. The original and reproduced data files are not included and remain subject to their respective source terms.

## Reference

Hassan, Tarek A., Stephan Hollander, Laurence van Lent, and Ahmed Tahoun. 2019. "Firm-Level Political Risk: Measurement and Effects." *The Quarterly Journal of Economics* 134 (4): 2135-2202. https://doi.org/10.1093/qje/qjz021.
