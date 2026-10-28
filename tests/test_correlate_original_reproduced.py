from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

import pytest

import correlate_original_reproduced as script

ORIGINAL_ROWS = [
    # gvkey, date, PRisk, PSentiment
    ("001004", "2020q1", 1.0, 4.0),
    ("001004", "2020q2", 2.0, 3.0),
    ("012345", "2020q1", 3.0, 2.0),
    ("012345", "2020q2", 5.0, 1.0),
]
CALLS = [
    # earningscallID, gvkey, start_time, risk, sentiment, nr_of_words
    ("call-1", "001004", "2020-01-20 13:30:00.000000000Z", 10.0, 40.0, 1000),
    ("call-2", "001004", "2020-04-20 13:30:00.000000000Z", 25.0, 30.0, 1000),
    ("call-3", "012345", "2020-01-21 13:30:00.000000000Z", 30.0, 20.0, 1000),
    ("call-4", "012345", "2020-04-21 13:30:00.000000000Z", 20.0, 10.0, 500),
    ("call-5", "012345", "2020-05-21 13:30:00.000000000Z", 40.0, 15.0, 1500),
    ("call-6", "", "2020-04-22 13:30:00.000000000Z", 99.0, 99.0, 1000),
]
SERIES_PAGE_PREFIX = "NLA_2026-10-22T000000_prisk-and-psentiment-v21_67e91380"
LAYOUTS = ["series_page_with_gvkey", "dataset_zip", "series_page_gzip"]


def write_text(path: Path, text: str, *, gzip_bytes: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if gzip_bytes:
        path.write_bytes(gzip.compress(text.encode()))
    else:
        path.write_text(text)


def csv_text(header: list[str], rows: list[list[object]], delimiter: str = ",") -> str:
    lines = [delimiter.join(header)]
    lines.extend(delimiter.join(str(value) for value in row) for row in rows)
    return "\n".join(lines) + "\n"


def write_original(path: Path) -> None:
    columns = [spec.original_column for spec in script.SERIES_SPECS]
    rows = []
    for gvkey, date, prisk, psentiment in ORIGINAL_ROWS:
        values = {"PRisk": prisk, "PSentiment": psentiment}
        rows.append([gvkey, date, *(values.get(column, "") for column in columns)])
    write_text(path, csv_text(["gvkey", "date", *columns], rows, delimiter="\t"))


def write_firmlevel(path: Path, *, with_gvkey: bool, gzip_bytes: bool = False) -> None:
    id_column = "gvkey" if with_gvkey else "earningscallID"
    rows = [
        [gvkey if with_gvkey else call_id, start_time, risk, sentiment, words]
        for call_id, gvkey, start_time, risk, sentiment, words in CALLS
    ]
    header = [id_column, "start_time", "risk", "sentiment", "nr_of_words"]
    write_text(path, csv_text(header, rows), gzip_bytes=gzip_bytes)


def write_crosswalk(path: Path, gvkeys: dict[str, str], *, gzip_bytes: bool = False) -> None:
    header = [
        "earningscallID",
        "gvkey_compustat",
        "sic_compustat",
        "sic_compustat_description",
    ]
    rows = [[call_id, gvkey, "7372", "Prepackaged Software"] for call_id, gvkey in gvkeys.items()]
    write_text(path, csv_text(header, rows), gzip_bytes=gzip_bytes)


def crosswalk_gvkeys() -> dict[str, str]:
    return {call_id: gvkey for call_id, gvkey, *_ in CALLS}


def write_layout(reproduced_dir: Path, layout: str, gvkeys: dict[str, str] | None = None) -> None:
    gvkeys = crosswalk_gvkeys() if gvkeys is None else gvkeys
    if layout == "series_page_with_gvkey":
        # Files downloaded before the October 2026 refresh still carry gvkey.
        path = reproduced_dir / "NLA_2026-06-24T114811_prisk-and-psentiment-v21_67e91380_firmlevel.csv"
        write_firmlevel(path, with_gvkey=True)
    elif layout == "dataset_zip":
        # The unzipped "Download dataset (ZIP)" bundle: gvkeys.csv.gz sits at its root.
        series_dir = reproduced_dir / "series" / "01-prisk-and-psentiment-v21-67e91380"
        write_firmlevel(series_dir / "firmlevel.csv.gz", with_gvkey=False, gzip_bytes=True)
        write_crosswalk(reproduced_dir / "gvkeys.csv.gz", gvkeys, gzip_bytes=True)
    elif layout == "series_page_gzip":
        # Series-page downloads can hold gzip bytes under a plain .csv name; GVKEYs
        # without zero padding still match the original's six-digit gvkey.
        write_firmlevel(
            reproduced_dir / f"{SERIES_PAGE_PREFIX}_firmlevel.csv",
            with_gvkey=False,
            gzip_bytes=True,
        )
        unpadded = {call_id: gvkey.lstrip("0") for call_id, gvkey in gvkeys.items()}
        write_crosswalk(
            reproduced_dir / f"{SERIES_PAGE_PREFIX}_gvkeys.csv",
            unpadded,
            gzip_bytes=True,
        )
    else:
        raise ValueError(f"Unknown layout: {layout}")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def run_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reproduced_dir: Path,
    *extra_args: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    original_file = tmp_path / "original" / "firmquarter_2022q1.csv"
    write_original(original_file)
    out_dir = tmp_path / "correlations"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "correlate_original_reproduced.py",
            "--original-file",
            str(original_file),
            "--reproduced-dir",
            str(reproduced_dir),
            "--out-dir",
            str(out_dir),
            *extra_args,
        ],
    )
    script.main()
    return (
        read_rows(out_dir / "firm_quarter_correlations.csv"),
        read_rows(out_dir / "quarterly_mean_correlations.csv"),
    )


def without_file(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{key: value for key, value in row.items() if key != "reproduced_file"} for row in rows]


def test_layouts_produce_identical_correlations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    results = {}
    for layout in LAYOUTS:
        reproduced_dir = tmp_path / layout / "reproduced"
        write_layout(reproduced_dir, layout)
        results[layout] = run_script(monkeypatch, tmp_path / layout, reproduced_dir)

    firm_quarter_rows, quarter_rows = results["series_page_with_gvkey"]
    assert [row["series"] for row in firm_quarter_rows] == ["PRisk", "PSentiment"]
    assert [row["n_pairs"] for row in firm_quarter_rows] == ["4", "4"]
    assert [row["n_pairs"] for row in quarter_rows] == ["2", "2"]
    assert {row["first_dateQ"] for row in firm_quarter_rows} == {"2020q1"}
    assert {row["last_dateQ"] for row in firm_quarter_rows} == {"2020q2"}
    assert (
        results["dataset_zip"][0][0]["reproduced_file"]
        == "01-prisk-and-psentiment-v21-67e91380/firmlevel.csv.gz"
    )
    assert results["series_page_gzip"][0][0]["reproduced_file"] == f"{SERIES_PAGE_PREFIX}_firmlevel.csv"
    for layout in LAYOUTS[1:]:
        assert without_file(results[layout][0]) == without_file(firm_quarter_rows)
        assert without_file(results[layout][1]) == without_file(quarter_rows)


def test_calls_missing_from_crosswalk_drop_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gvkeys = crosswalk_gvkeys()
    del gvkeys["call-3"]
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip", gvkeys)

    firm_quarter_rows, _ = run_script(monkeypatch, tmp_path, reproduced_dir)

    assert [row["n_pairs"] for row in firm_quarter_rows] == ["3", "3"]
    assert "2 calls without a GVKEY" in capsys.readouterr().out


def test_crosswalk_from_another_download_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip", {"other-call": "001004"})

    with pytest.raises(ValueError, match="No earningscallID in .* is present in the crosswalk"):
        run_script(monkeypatch, tmp_path, reproduced_dir)


def test_missing_crosswalk_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip")
    (reproduced_dir / "gvkeys.csv.gz").unlink()

    with pytest.raises(FileNotFoundError, match="No GVKEY crosswalk found"):
        run_script(monkeypatch, tmp_path, reproduced_dir)


def test_crosswalk_is_found_from_series_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip")

    firm_quarter_rows, _ = run_script(monkeypatch, tmp_path, reproduced_dir / "series")

    assert [row["n_pairs"] for row in firm_quarter_rows] == ["4", "4"]


def test_gvkeys_file_overrides_discovery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip")
    gvkeys_file = tmp_path / "elsewhere" / "gvkeys.csv.gz"
    gvkeys_file.parent.mkdir()
    (reproduced_dir / "gvkeys.csv.gz").rename(gvkeys_file)

    firm_quarter_rows, _ = run_script(
        monkeypatch, tmp_path, reproduced_dir, "--gvkeys-file", str(gvkeys_file)
    )

    assert [row["n_pairs"] for row in firm_quarter_rows] == ["4", "4"]


def test_multiple_crosswalks_are_rejected(tmp_path: Path) -> None:
    write_crosswalk(tmp_path / "gvkeys.csv", crosswalk_gvkeys())
    write_crosswalk(tmp_path / f"{SERIES_PAGE_PREFIX}_gvkeys.csv", crosswalk_gvkeys())

    with pytest.raises(ValueError, match="Multiple GVKEY crosswalks found"):
        script.resolve_gvkey_crosswalk(tmp_path, None)


def test_read_gvkey_crosswalk_rejects_conflicting_gvkeys(tmp_path: Path) -> None:
    path = tmp_path / "gvkeys.csv"
    write_text(
        path,
        csv_text(
            ["earningscallID", "gvkey_compustat"],
            [["call-1", "001004"], ["call-1", "001005"]],
        ),
    )

    with pytest.raises(ValueError, match="maps earningscallID call-1 to more than one gvkey"):
        script.read_gvkey_crosswalk(path)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("001004", "001004"),
        ("1004", "001004"),
        ("1004.0", "001004"),
        (" 012345 ", "012345"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_gvkey(value: str | None, expected: str) -> None:
    assert script.normalize_gvkey(value) == expected


@pytest.mark.parametrize("value", ["   ", "NaN", "NULL", "N/A", "NA", "None", "<NA>", "."])
def test_normalize_gvkey_recognizes_missing_markers(value: str) -> None:
    assert script.normalize_gvkey(value) == ""


@pytest.mark.parametrize(
    "value",
    ["broken", "1004.5", "-1", "inf", "9223372036854775808", "1.0000000000000001"],
)
def test_normalize_gvkey_rejects_malformed_identifiers(value: str) -> None:
    with pytest.raises(ValueError, match="invalid gvkey"):
        script.normalize_gvkey(value)


@pytest.mark.parametrize("gvkeys", [["", "1004", "001004"], ["1004", "001004", ""]])
def test_missing_duplicate_does_not_replace_known_gvkey(tmp_path: Path, gvkeys: list[str]) -> None:
    path = tmp_path / "gvkeys.csv"
    write_text(
        path,
        csv_text(["earningscallID", "gvkey_compustat"], [["call-1", key] for key in gvkeys]),
    )

    assert script.read_gvkey_crosswalk(path) == {"call-1": "001004"}


def test_missing_gvkeys_do_not_create_a_fictitious_firm(tmp_path: Path) -> None:
    path = tmp_path / "gvkeys.csv"
    write_crosswalk(path, {"call-1": "NaN", "call-2": "NULL"})
    calls = tmp_path / "firmlevel.csv"
    write_text(
        calls,
        "earningscallID,start_time,risk,nr_of_words\ncall-1,2020-01-01,1,1000\ncall-2,2020-01-02,10,1000\n",
    )
    crosswalk = script.read_gvkey_crosswalk(path)

    loaded = script.load_reproduced_series(calls, script.SERIES_SPECS[0], crosswalk)

    assert crosswalk == {"call-1": "", "call-2": ""}
    assert loaded.values == {}
    assert loaded.calls_without_gvkey == 2


def test_blank_call_ids_cannot_contaminate_a_firm_quarter(tmp_path: Path) -> None:
    path = tmp_path / "gvkeys.csv"
    write_crosswalk(path, {"   ": "001004", "": "001005", "call-1": "001004"})
    calls = tmp_path / "firmlevel.csv"
    write_text(
        calls,
        "earningscallID,start_time,risk,nr_of_words\n"
        "   ,2020-01-01,100,1000\n,2020-01-01,100,1000\n call-1 ,2020-01-01,1,1000\n",
    )
    crosswalk = script.read_gvkey_crosswalk(path)

    loaded = script.load_reproduced_series(calls, script.SERIES_SPECS[0], crosswalk)

    assert crosswalk == {"call-1": "001004"}
    assert loaded.values == {("001004", "2020q1"): 0.001}
    assert loaded.calls_without_gvkey == 2


def test_all_missing_call_ids_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "firmlevel.csv"
    write_text(path, "earningscallID,start_time,risk,nr_of_words\n   ,2020-01-01,1,1000\n")

    loaded = script.load_reproduced_series(path, script.SERIES_SPECS[0], {"other-call": "001004"})

    assert loaded.values == {}
    assert loaded.calls_without_gvkey == 1


def test_known_calls_without_gvkeys_produce_zero_pairs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(
        reproduced_dir,
        "dataset_zip",
        {call_id: "NaN" for call_id in crosswalk_gvkeys()},
    )

    firm_quarter_rows, quarter_rows = run_script(monkeypatch, tmp_path, reproduced_dir)

    assert [row["n_pairs"] for row in firm_quarter_rows] == ["0", "0"]
    assert [row["n_pairs"] for row in quarter_rows] == ["0", "0"]
    output = capsys.readouterr().out
    assert "0 calls with a GVKEY" in output
    assert "6 calls without a GVKEY" in output


@pytest.mark.parametrize("source", ["crosswalk", "original", "firmlevel"])
def test_invalid_gvkey_reports_file_and_row(tmp_path: Path, source: str) -> None:
    path = tmp_path / f"{source}.csv"
    with pytest.raises(ValueError, match="row 3: invalid gvkey") as error:
        if source == "crosswalk":
            write_crosswalk(path, {"call-1": "001004", "call-2": "broken"})
            script.read_gvkey_crosswalk(path)
        elif source == "original":
            write_text(path, "gvkey\tdate\tPRisk\n001004\t2020q1\t1\nbroken\t2020q2\t2\n")
            script.read_original(path, {"PRisk"})
        else:
            write_text(
                path,
                "gvkey,start_time,risk,nr_of_words\n001004,2020-01-01,1,1000\nbroken,2020-04-01,2,1000\n",
            )
            script.load_reproduced_series(path, script.SERIES_SPECS[0])

    assert str(path) in str(error.value)
    assert "broken" in str(error.value)


@pytest.mark.parametrize("missing", ["gvkey", "date"])
def test_original_requires_join_key_columns(tmp_path: Path, missing: str) -> None:
    path = tmp_path / "original.csv"
    fields = [field for field in ["gvkey", "date", "PRisk"] if field != missing]
    write_text(path, "\t".join(fields) + "\n")
    with pytest.raises(ValueError, match=f"missing columns: {missing}"):
        script.read_original(path, {"PRisk"})


def test_duplicate_original_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "original.csv"
    write_text(path, "gvkey\tdate\tPRisk\n1004\t2020q1\t1\n001004\t2020q1\t2\n")
    with pytest.raises(ValueError, match="duplicate original firm-quarter"):
        script.read_original(path, {"PRisk"})


def test_prisk_uses_ratio_of_sums_with_unequal_word_counts(tmp_path: Path) -> None:
    path = tmp_path / "calls.csv"
    write_text(
        path,
        "gvkey,start_time,risk,nr_of_words\n1004,2020-01-01,10,1000\n1004,2020-02-01,60,3000\n",
    )
    loaded = script.load_reproduced_series(path, script.SERIES_SPECS[0])
    # 70 / 4000 = 0.0175; the unweighted alternative would be 0.015.
    assert loaded.values == {("001004", "2020q1"): 0.0175}


def test_compare_series_matches_before_computing_quarter_means() -> None:
    # Matched quarter means: reproduced (1, 2, 4), original (2, 4, 3).
    original = {
        ("a", "2020q1"): 0.0,
        ("b", "2020q1"): 4.0,
        ("a", "2020q2"): 4.0,
        ("a", "2020q3"): 3.0,
        ("original-only", "2020q1"): 10000.0,
    }
    reproduced = {
        ("a", "2020q1"): 0.0,
        ("b", "2020q1"): 2.0,
        ("a", "2020q2"): 2.0,
        ("a", "2020q3"): 4.0,
        ("reproduced-only", "2020q2"): -10000.0,
    }
    result = script.compare_series(original, reproduced)
    assert result.n_pairs == 4
    assert result.n_quarters == 3
    assert (result.first_dateq, result.last_dateq) == ("2020q1", "2020q3")
    # Centered sums: cross-product 6, sums of squares 8 and 10.75.
    assert result.firm_pearson == pytest.approx(6 / (86**0.5))
    assert result.quarter_pearson == pytest.approx((3 / 28) ** 0.5)


@pytest.mark.parametrize(
    "pairs, expected",
    [
        ([], None),
        ([(1.0, 2.0)], None),
        ([(1.0, 2.0), (1.0, 3.0)], None),
        ([(1.0, 3.0), (2.0, 2.0), (3.0, 1.0)], -1.0),
    ],
)
def test_pearson_edge_cases(pairs: list[tuple[float, float]], expected: float | None) -> None:
    assert script.pearson(pairs) == expected


def test_empty_comparison_has_no_statistics() -> None:
    result = script.compare_series({("a", "2020q1"): 1.0}, {})
    assert result.n_pairs == result.n_quarters == 0
    assert result.firm_pearson is result.quarter_pearson is None
    assert result.first_dateq == result.last_dateq == ""


def test_manifest_identifies_used_inputs_and_deduplicates_series_files(
    tmp_path: Path,
) -> None:
    import hashlib

    original = tmp_path / "original.csv"
    original.write_text("gvkey\tdate\tPRisk\n1004\t2020q1\t1\n")
    calls = tmp_path / "calls.csv"
    write_firmlevel(calls, with_gvkey=False, gzip_bytes=True)
    crosswalk = tmp_path / "gvkeys.csv"
    write_crosswalk(crosswalk, crosswalk_gvkeys())
    output = tmp_path / "manifest.csv"
    script.write_manifest(output, original, [calls, calls], crosswalk)
    rows = read_rows(output)
    assert [row["role"] for row in rows] == [
        "original_csv",
        "reproduced_csv",
        "gvkey_crosswalk",
    ]
    assert [int(row["rows"]) for row in rows] == [1, len(CALLS), len(CALLS)]
    for row, path in zip(rows, [original, calls, crosswalk]):
        assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert int(row["bytes"]) == path.stat().st_size
    script.write_manifest(output, original, [calls], None)
    assert len(read_rows(output)) == 2
