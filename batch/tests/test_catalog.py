"""catalog.py reads data/catalog.db (schema owned by scripts/seed_catalog.py,
a separate part of the repo with no shared types with batch/ — see that
module's docstring) via a hardcoded SELECT. Nothing here would catch a
silent column rename in that schema at import time or in CI unless a
test actually opens the real database and checks the columns it reads
are still there, so that's what this does instead of a synthetic
fixture."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from thing_transfer_batch.catalog import item_categories

_REAL_DB = Path(__file__).resolve().parents[2] / "data" / "catalog.db"


@pytest.mark.skipif(not _REAL_DB.exists(), reason="data/catalog.db not present — run scripts/seed_catalog.py")
def test_item_categories_reads_real_catalog_schema():
    categories = item_categories(_REAL_DB)
    assert len(categories) > 0
    item_id, category = next(iter(categories.items()))
    assert isinstance(item_id, str) and item_id
    assert isinstance(category, str) and category.startswith("ITEM_CATEGORY_")


def test_item_categories_raises_if_db_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        item_categories(tmp_path / "does-not-exist.db")
