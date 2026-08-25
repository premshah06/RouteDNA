"""Sync ClickHouse HTTP-interface reader, JSON-flavored.

batch/thing_transfer_batch/clickhouse.py already has an HTTP-over-TSV
writer/scalar-reader for the batch layer's needs. This service only
reads, and every query here returns multiple columns per row (not a
single scalar), so it uses ClickHouse's FORMAT JSONEachRow instead of
parsing TSV by hand.
"""

import json
import os

import httpx

CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "thing-transfer-local")


def query_rows(sql: str) -> list[dict]:
    """Runs `sql` (must not itself specify a FORMAT clause) and returns
    one dict per result row. Empty result set -> empty list, not an
    error — every caller here is asking about a facility that may
    genuinely have zero matching rows (a package with no alerts, a
    quiet hour)."""
    resp = httpx.post(
        CLICKHOUSE_URL,
        params={"query": f"{sql}\nFORMAT JSONEachRow"},
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
        timeout=30.0,
    )
    resp.raise_for_status()
    text = resp.text.strip()
    if not text:
        return []
    return [json.loads(line) for line in text.splitlines()]
