"""Lightweight schema sync for local/dev databases.

`create_all` only creates missing tables. This also adds columns that were added to models after the
database was created, so an existing bizos.db keeps its data. Replace with Alembic before production.
"""
from sqlalchemy import Boolean, inspect, text
from sqlalchemy.engine import Engine

from app.core.database import Base


def _default_sql(col, dialect: str) -> str:
    d = col.default.arg if col.default is not None and not callable(col.default.arg) else None
    if d is None:
        return ""
    if isinstance(col.type, Boolean) or isinstance(d, bool):
        if dialect == "sqlite":
            return f" DEFAULT {1 if d else 0}"
        return f" DEFAULT {'TRUE' if d else 'FALSE'}"
    if isinstance(d, (int, float)):
        return f" DEFAULT {d}"
    if isinstance(d, str):
        return " DEFAULT '" + d.replace("'", "''") + "'"
    return ""


def sync_schema(engine: Engine) -> list[str]:
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}{_default_sql(col, engine.dialect.name)}'
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added
