# PRisk Reproduction Correlations

This repository contains two runnable files for comparing reproduced PRisk outputs
against the original firm-quarter score file.

## Environment

The correlation script uses only the Python standard library. The notebook needs
Jupyter tooling, which is declared as the optional `notebook` dependency group in
`pyproject.toml`.

Create an environment with:

```sh
python3 -m venv venv
venv/bin/python -m pip install -e ".[notebook]"
```

## `scripts/correlate_original_reproduced.py`

Command-line runner for the correlation workflow.

It reads:

- `data/original/scores/firmquarter_2022q1.csv`
- `data/reproduced_v2/*_firmlevel.csv`
- `data/reproduced_v2.1/*_firmlevel.csv`

It computes reproduced measures from raw numerator columns:

- `risk / nr_of_words` for `PRisk` and all `PRiskT_*` topic series
- `sentiment / nr_of_words` for `PSentiment`

Rows are aggregated to `gvkey`-`dateQ` before correlation with the original
score columns. The script writes both firm-quarter correlations and quarterly
mean correlations to `data/correlations/`.

Run it with:

```sh
python3 scripts/correlate_original_reproduced.py
```

You can also pass one or more reproduced directories explicitly:

```sh
python3 scripts/correlate_original_reproduced.py \
  --reproduced-dir data/reproduced_v2 \
  --reproduced-dir data/reproduced_v2.1
```

## `reproduced_final_correlations.ipynb`

Notebook wrapper around the same command-line runner.

Use it when you want to rerun the correlations from Jupyter/IPython and inspect
the result tables interactively. Running all cells will:

1. Locate the repository root.
2. Execute `scripts/correlate_original_reproduced.py`.
3. Show the generated output files.
4. Display the combined `gvkey`-`dateQ` and `dateQ` correlation tables.
5. Display the `reproduced_v2.1` minus `reproduced_v2` correlation deltas.

The notebook intentionally calls the script instead of duplicating the
correlation implementation, so both entrypoints produce the same CSV outputs.

## Outputs

The main generated files are:

- `data/correlations/reproduced_v2_gvkey_dateq_correlations.csv`
- `data/correlations/reproduced_v2_dateq_correlations.csv`
- `data/correlations/reproduced_v2.1_gvkey_dateq_correlations.csv`
- `data/correlations/reproduced_v2.1_dateq_correlations.csv`
- `data/correlations/reproduced_versions_gvkey_dateq_correlations.csv`
- `data/correlations/reproduced_versions_dateq_correlations.csv`

The `data/` directory is ignored by git, so these CSVs are local generated
artifacts.
