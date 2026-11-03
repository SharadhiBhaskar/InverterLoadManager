import sqlite3
from pathlib import Path

folder = Path(__file__).parent
db_path = folder / "inverter.db"
schema_sql = (folder / "schema.sql").read_text(encoding="utf-8")

connection = sqlite3.connect(db_path)
connection.executescript(schema_sql)
connection.commit()
connection.close()

print(f"Database ready: {db_path}")