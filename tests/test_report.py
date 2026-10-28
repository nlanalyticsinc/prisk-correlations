from pathlib import Path

from render_headline import render_headline_table


def test_readme_headline_matches_committed_outputs() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text()
    table = readme.split("<!-- headline-table:start -->\n")[1].split("\n<!-- headline-table:end -->")[0]
    assert table == render_headline_table(root / "data/correlations")
