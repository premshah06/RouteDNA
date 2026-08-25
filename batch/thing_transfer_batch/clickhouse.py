"""Sync ClickHouse HTTP-interface writer for Dagster assets.

Same TabSeparated-over-HTTP convention as
warehouse/clickhouse_loader/loader.py (see that module's docstring for
why: ClickHouse's native Kafka table engine can't decode this
platform's base64-wrapped protobuf, so every writer here goes through
plain HTTP INSERT instead). This one is sync rather than async because
Dagster asset functions are sync by default and each of these assets
runs once per materialization, not in a tight streaming loop — there's
no throughput reason to pay for asyncio here.
"""

import os

import httpx

CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "thing-transfer-local")


def _escape(value) -> str:
    return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def rows_to_tsv(rows: list, columns: list) -> str:
    lines = ["\t".join(_escape(row[col]) for col in columns) for row in rows]
    return "\n".join(lines) + "\n"


def insert_rows(table: str, columns: list, rows: list) -> int:
    """Returns the number of rows inserted (0 if rows is empty — a
    no-op, not an error, since an empty-but-valid day is a real input
    the batch layer must handle, e.g. a facility closed for a holiday)."""
    if not rows:
        return 0
    query = f"INSERT INTO {table} ({', '.join(columns)}) FORMAT TabSeparated"
    resp = httpx.post(
        CLICKHOUSE_URL,
        params={"query": query},
        content=rows_to_tsv(rows, columns),
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
        timeout=30.0,
    )
    resp.raise_for_status()
    return len(rows)


def query_scalar(sql: str) -> str:
    """For the reconciliation asset's read against the `alerts` table
    (streaming's output) — a single-value query, e.g. a COUNT(*)."""
    resp = httpx.post(
        CLICKHOUSE_URL,
        content=sql,
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.text.strip()
