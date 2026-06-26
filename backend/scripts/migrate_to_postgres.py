"""One-off: copy all data from the local SQLite DB into a target Postgres DB.

Usage:
    SOURCE_SQLITE=sqlite:///./limitless.db \
    TARGET_DATABASE_URL=postgresql://... \
    python -m scripts.migrate_to_postgres

Uses the typed SQLAlchemy model tables for both read and write so JSON,
boolean, and datetime columns convert correctly between dialects. Big tables
are streamed in primary-key-ordered batches to bound memory. Integer PKs are
preserved and the owning sequences are reset afterward. Idempotent-ish: each
table is truncated on the target before load (run against an empty/throwaway
DB or a DB you intend to overwrite).
"""

import os
import sys

from sqlalchemy import create_engine, func, insert, select, text

from app.db.models import Base, Chunk, Lifelog, PrivacyEvent, SyncState, Utterance

BATCH = 2000

# FK-safe load order. (model, has_int_autoincrement_pk)
TABLES = [
    (Lifelog, False),
    (Utterance, True),
    (Chunk, True),
    (PrivacyEvent, True),
    (SyncState, False),
]


def _normalize(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


def main() -> None:
    source_url = os.environ.get("SOURCE_SQLITE", "sqlite:///./limitless.db")
    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not target_url:
        sys.exit("TARGET_DATABASE_URL is required")
    target_url = _normalize(target_url)

    src = create_engine(source_url)
    dst = create_engine(target_url)

    # Truncate target tables (reverse FK order) for a clean reload.
    with dst.begin() as c:
        names = ", ".join(m.__tablename__ for m, _ in reversed(TABLES))
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    print(f"Truncated: {names}")

    for model, int_pk in TABLES:
        table = model.__table__
        pk = list(table.primary_key.columns)[0]

        with src.connect() as sc:
            total = sc.execute(select(func.count()).select_from(table)).scalar()
        print(f"\n{table.name}: {total} rows")
        if not total:
            continue

        moved = 0
        last = None
        while True:
            stmt = select(table).order_by(pk).limit(BATCH)
            if last is not None:
                stmt = stmt.where(pk > last)
            with src.connect() as sc:
                rows = sc.execute(stmt).mappings().all()
            if not rows:
                break
            payload = [dict(r) for r in rows]
            with dst.begin() as dc:
                dc.execute(insert(table), payload)
            last = rows[-1][pk.name]
            moved += len(rows)
            print(f"  {table.name}: {moved}/{total}", end="\r", flush=True)
        print(f"  {table.name}: {moved}/{total} done")

        # Reset the identity sequence so future inserts don't collide.
        if int_pk:
            with dst.begin() as dc:
                dc.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk.name}'), "
                        f"COALESCE((SELECT MAX({pk.name}) FROM {table.name}), 1))"
                    )
                )

    # Verify row counts match.
    print("\n=== verification ===")
    ok = True
    for model, _ in TABLES:
        t = model.__table__
        with src.connect() as sc:
            s = sc.execute(select(func.count()).select_from(t)).scalar()
        with dst.connect() as dc:
            d = dc.execute(select(func.count()).select_from(t)).scalar()
        flag = "OK" if s == d else "MISMATCH"
        if s != d:
            ok = False
        print(f"  {t.name}: source={s} target={d} [{flag}]")
    print("RESULT:", "ALL MATCH" if ok else "MISMATCH — investigate")


if __name__ == "__main__":
    main()
