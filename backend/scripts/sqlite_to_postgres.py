"""Copy every company's data from the local SQLite file into a (new, empty) PostgreSQL database.

Run on the server (or anywhere that can reach Postgres):
    python -m scripts.sqlite_to_postgres --sqlite bizos.db --postgres postgresql+psycopg2://bizos:PASS@localhost:5432/bizos

Tables are copied parents-first, then the id sequences are moved past the copied ids.
"""
import argparse
import os
import sys

sys.path.insert(0, ".")

from sqlalchemy import create_engine, func, insert, select, text  # noqa: E402

import app.models  # noqa: E402,F401  (registers every table on Base.metadata)
from app.core.database import Base  # noqa: E402

BATCH = 1000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, help="path to bizos.db")
    ap.add_argument("--postgres", required=True, help="target SQLAlchemy URL")
    args = ap.parse_args()
    if not os.path.isfile(args.sqlite):
        sys.exit(f"SQLite file not found: {args.sqlite}")

    src = create_engine(f"sqlite:///{args.sqlite}")
    dst = create_engine(args.postgres)
    Base.metadata.create_all(dst)

    with dst.connect() as c:
        if c.execute(select(func.count()).select_from(Base.metadata.tables["companies"])).scalar():
            sys.exit("The target database already has companies in it. Use an empty database.")

    with src.connect() as s, dst.begin() as d:
        for table in Base.metadata.sorted_tables:
            src_cols = {r[1] for r in s.execute(text(f"PRAGMA table_info({table.name})"))}
            if not src_cols:
                continue  # table didn't exist in the old file
            cols = [c for c in table.columns if c.name in src_cols]
            rows = s.execute(select(*cols)).mappings().all()
            for i in range(0, len(rows), BATCH):
                d.execute(insert(table), [dict(r) for r in rows[i:i + BATCH]])
            print(f"{table.name}: {len(rows)}")
        if dst.dialect.name == "postgresql":
            for table in Base.metadata.sorted_tables:
                if "id" in table.c:
                    d.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), COALESCE((SELECT MAX(id) FROM {table.name}), 0) + 1, false)"))
    print("Done.")


if __name__ == "__main__":
    main()
