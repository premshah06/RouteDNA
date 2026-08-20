"""Generates a large, realistic item catalog into data/catalog.db.

Not a one-off script output — this is the actual reference dataset every
service reads item_id -> name/category/sku/weight/stock from (see
services/common/catalog.py for the read side). Regenerate with:
    python3 scripts/seed_catalog.py [--count N]

Deterministic given the same --seed, so re-running produces the same
catalog rather than drifting on every regeneration.
"""

import argparse
import random
import sqlite3
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.db"

# Category -> (brand pool, product-noun pool, weight range kg). Grounded
# in real retail categories rather than generic "Item {n}" placeholders,
# so the frontend (Checkpoint 7) and any operator looking at an alert
# sees something a person would actually recognize.
CATEGORIES = {
    "ITEM_CATEGORY_ELECTRONICS": {
        "brands": ["Vantix", "Corelume", "Nexdrive", "Aeropix", "Solace", "Bytewave"],
        "nouns": ["Wireless Mouse", "USB-C Hub", "Bluetooth Speaker", "Noise-Cancelling Headphones",
                  "Portable SSD 1TB", "Webcam 1080p", "Mechanical Keyboard", "Power Bank 20000mAh",
                  "Smart Plug", "HDMI Cable 2m"],
        "weight_range": (0.05, 2.5),
    },
    "ITEM_CATEGORY_APPAREL": {
        "brands": ["Northloom", "Cascade & Co", "Drift Supply", "Marrow", "Fieldstitch"],
        "nouns": ["Cotton T-Shirt", "Merino Wool Sweater", "Denim Jacket", "Running Shorts",
                  "Wool Beanie", "Rain Shell", "Canvas Tote", "Ankle Socks 3-Pack", "Fleece Vest"],
        "weight_range": (0.1, 1.2),
    },
    "ITEM_CATEGORY_HOME_GOODS": {
        "brands": ["Hearthline", "Kindle & Oak", "Basin", "Loamware", "Trestle"],
        "nouns": ["Ceramic Mug Set", "Cast Iron Skillet", "Linen Throw Blanket", "LED Desk Lamp",
                  "Bamboo Cutting Board", "Storage Ottoman", "Glass Food Containers", "Wall Clock"],
        "weight_range": (0.2, 6.0),
    },
    "ITEM_CATEGORY_GROCERY": {
        "brands": ["Millbrook", "Sunvale", "Harvest Row", "Coastal Pantry"],
        "nouns": ["Organic Rolled Oats", "Extra Virgin Olive Oil", "Roasted Almonds", "Dark Chocolate Bar",
                  "Green Tea 100ct", "Sparkling Water 12-Pack", "Honey 500g", "Trail Mix"],
        "weight_range": (0.2, 4.5),
    },
    "ITEM_CATEGORY_BOOKS_MEDIA": {
        "brands": ["Fernwood Press", "Ledger House", "Northbind Editions"],
        "nouns": ["Hardcover Novel", "Paperback Cookbook", "Vinyl Record", "Board Game",
                  "Puzzle 1000pc", "Journal Notebook", "Graphic Novel"],
        "weight_range": (0.15, 1.5),
    },
    "ITEM_CATEGORY_TOYS": {
        "brands": ["Puffling", "Tinker & Bloom", "Wanderkid", "Blockworks"],
        "nouns": ["Building Block Set", "Plush Bear", "Remote Control Car", "Wooden Puzzle",
                  "Art Supply Kit", "Kite", "Action Figure"],
        "weight_range": (0.1, 3.0),
    },
    "ITEM_CATEGORY_HEALTH_BEAUTY": {
        "brands": ["Clearwell", "Birchwater", "Tidal Care", "Meadowlark"],
        "nouns": ["Vitamin C Serum", "Electric Toothbrush", "Shampoo Bar", "Sunscreen SPF50",
                  "Hand Cream", "Essential Oil Diffuser", "Bamboo Toothbrush 4-Pack"],
        "weight_range": (0.05, 1.0),
    },
    "ITEM_CATEGORY_AUTOMOTIVE": {
        "brands": ["Ironclad", "Roadrun", "Torque Line", "Farview"],
        "nouns": ["Microfiber Towel Set", "Tire Pressure Gauge", "Dash Cam", "Car Phone Mount",
                  "Jump Starter Pack", "Floor Mat Set"],
        "weight_range": (0.1, 5.0),
    },
}


def generate_catalog(count: int, seed: int):
    rng = random.Random(seed)
    categories = list(CATEGORIES.items())
    sku_counters = {cat_name: 0 for cat_name, _ in categories}
    rows = []
    for i in range(count):
        cat_name, cat = categories[i % len(categories)]
        brand = rng.choice(cat["brands"])
        noun = rng.choice(cat["nouns"])
        variant = rng.randint(1, 999)
        name = f"{brand} {noun} #{variant}"
        # Per-category running counter, not a random draw: guarantees
        # SKU uniqueness by construction instead of relying on a random
        # space large enough to make collisions merely unlikely (a
        # randint(10000, 99999) suffix collides with near-certainty by
        # the birthday paradox once a category passes a few hundred
        # items, let alone the ~6k/category this generates by default).
        sku_counters[cat_name] += 1
        sku = f"{cat_name.removeprefix('ITEM_CATEGORY_')[:3]}-{sku_counters[cat_name]:06d}"
        weight = round(rng.uniform(*cat["weight_range"]), 3)
        stock = rng.randint(0, 5000)
        item_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"thing-transfer-catalog-{seed}-{i}"))
        rows.append((item_id, name, sku, cat_name, weight, stock))
    return rows


def write_catalog(rows, db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE items (
                item_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sku TEXT NOT NULL,
                category TEXT NOT NULL,
                unit_weight_kg REAL NOT NULL,
                stock_quantity INTEGER NOT NULL,
                catalog_updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("CREATE UNIQUE INDEX idx_items_sku ON items(sku)")
        conn.execute("CREATE INDEX idx_items_category ON items(category)")
        conn.executemany(
            "INSERT INTO items (item_id, name, sku, category, unit_weight_kg, stock_quantity) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Seed the item catalog")
    parser.add_argument("--count", type=int, default=50_000, help="number of catalog items to generate")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed, for reproducible catalogs")
    parser.add_argument("--out", type=Path, default=DB_PATH, help="output sqlite path")
    args = parser.parse_args()

    rows = generate_catalog(args.count, args.seed)
    write_catalog(rows, args.out)
    print(f"wrote {len(rows)} items to {args.out}")


if __name__ == "__main__":
    main()
