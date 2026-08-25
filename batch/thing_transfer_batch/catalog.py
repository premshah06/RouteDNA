"""Read-only item_id -> category lookup for the batch layer.

Deliberately not reusing services/common/catalog.py: that module
returns packagepb.v1.item_pb2.Item protos, which would pull the
protobuf-generated stubs (and their protobuf==4.23.4 pin) into this
project's separate venv — exactly the dependency coupling batch/ was
split out to avoid (see batch/requirements.txt). All this needs is a
plain dict, so a minimal sqlite read gets it without the import.
"""

import os
import sqlite3
from pathlib import Path

_DEFAULT_DB_PATH = Path(
    os.environ.get("CATALOG_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "catalog.db"))
)


def item_categories(db_path: Path = _DEFAULT_DB_PATH) -> dict:
    """item_id -> category string (e.g. 'ITEM_CATEGORY_ELECTRONICS').

    The `items` table's schema is authoritatively defined in
    scripts/seed_catalog.py, not here — this is a schema-crossing
    boundary with no shared types (see module docstring), so a column
    rename there wouldn't be caught until this query starts failing at
    runtime. batch/tests/test_catalog.py opens the real catalog.db and
    asserts these columns still exist, specifically to catch that
    class of drift in CI rather than in a live batch run.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"catalog db not found at {db_path} — run scripts/seed_catalog.py first")
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT item_id, category FROM items").fetchall()
        return dict(rows)
    finally:
        conn.close()
