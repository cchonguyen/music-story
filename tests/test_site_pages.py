"""W10 acceptance (structure only; `npm run build` is the visual check): every mart
has a data loader, every chapter page exists and only uses loaders that exist.
Skipped until site/src/artists.md exists."""

import re

import pytest

from pipeline import config
from pipeline.site_data import fixture_marts

SRC = config.REPO_ROOT / "site" / "src"
PAGES = ["index", "artists", "songs", "genres", "habits", "places"]

if not (SRC / "artists.md").exists():
    pytest.skip("W10 not built yet", allow_module_level=True)


@pytest.fixture(scope="module")
def marts(fixture_db_path):
    con = fixture_marts(fixture_db_path)
    names = [r[0].removeprefix("mart_") for r in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'mart_%'").fetchall()]
    con.close()
    return sorted(names)


def test_one_loader_per_mart(marts):
    for name in marts:
        loader = SRC / "data" / f"{name}.json.sh"
        assert loader.exists(), f"missing loader for mart_{name}"
        assert f"pipeline.site_data {name}" in loader.read_text()


@pytest.mark.parametrize("page", PAGES)
def test_page_exists_and_uses_real_loaders(page):
    text = (SRC / f"{page}.md").read_text()
    used = re.findall(r'FileAttachment\("data/([a-z_]+)\.json"\)', text)
    assert used, f"{page}.md loads no data"
    for name in used:
        assert (SRC / "data" / f"{name}.json.sh").exists(), f"{page}.md uses missing data/{name}.json"


def test_pages_are_in_the_sidebar():
    config_js = (config.REPO_ROOT / "site" / "observablehq.config.js").read_text()
    for page in PAGES[1:]:
        assert f'"/{page}"' in config_js or f"'/{page}'" in config_js, f"{page} not in pages"
