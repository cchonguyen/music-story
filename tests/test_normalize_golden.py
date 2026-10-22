"""W2 acceptance: normalisation golden cases. Skipped until pipeline/normalize.py exists."""

import pytest

normalize = pytest.importorskip("pipeline.normalize", reason="W2 not built yet")

from golden.normalize_cases import ARTIST_CASES, TITLE_CASES


@pytest.mark.parametrize("raw,full,base,mix", TITLE_CASES, ids=[c[0] for c in TITLE_CASES])
def test_normalize_title(raw, full, base, mix):
    assert normalize.normalize_title(raw) == (full, base, mix)


@pytest.mark.parametrize("raw,expected", ARTIST_CASES, ids=[c[0] for c in ARTIST_CASES])
def test_normalize_artist(raw, expected):
    assert normalize.normalize_artist(raw) == expected
