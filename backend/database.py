import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("INVERTER_DB", Path(__file__).parent / "inverter.db"))
CAPACITY_WATTS = 800
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_initialized = set()


def init_db():
    if str(DB_PATH) in _initialized and DB_PATH.exists():
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    try:
        connection.executescript(schema_sql)
    finally:
        connection.close()
    _initialized.add(str(DB_PATH))


def get_connection():
    init_db()
    connection = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def transaction(connection):
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def list_appliances(connection):
    rows = connection.execute(
        """
        SELECT id, name, wattage, priority, state, shed_at
        FROM appliances
        ORDER BY priority, id
        """
    ).fetchall()
    return [dict(row) for row in rows]


if __name__ == "__main__":
    connection = get_connection()
    try:
        print(list_appliances(connection))
    finally:
        connection.close()
