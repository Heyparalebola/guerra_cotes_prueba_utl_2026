import sqlite3
import sys
import unicodedata
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "db" / "puestos_2026.db"
SCRAPER_DIR = ROOT_DIR / "scraper"
sys.path.insert(0, str(SCRAPER_DIR))


def normalize_name(value):
    """Normalize a name for stable matching."""
    raw = unicodedata.normalize("NFKD", str(value or ""))
    clean = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return " ".join(clean.upper().split())


def connect_database():
    """Open the existing SQLite database."""
    if not DB_PATH.exists():
        raise SystemExit("No existe db/puestos_2026.db. Ejecute primero scraper/scraper.py")
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def refresh_candidate_names(connection):
    """Update candidate names that need normalization."""
    rows = connection.execute("SELECT id, candidate_name FROM candidates").fetchall()
    updated = 0
    for candidate_id, candidate_name in rows:
        normalized_name = normalize_name(candidate_name)
        current_name = connection.execute(
            "SELECT normalized_name FROM candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()[0]
        if current_name == normalized_name:
            continue
        connection.execute(
            "UPDATE candidates SET normalized_name = ? WHERE id = ?",
            (normalized_name, candidate_id),
        )
        updated += 1
    return len(rows), updated


def count_parties(connection):
    """Count unique parties loaded by party code."""
    return connection.execute("SELECT COUNT(*) FROM parties").fetchone()[0]


def collect_last_load(connection, payload_count):
    """Summarize the latest scraper load by endpoint."""
    if payload_count == 0:
        return 0, 0
    row = connection.execute(
        """
        SELECT COALESCE(SUM(inserted_rows), 0), COALESCE(SUM(skipped_rows), 0)
        FROM (
            SELECT inserted_rows, skipped_rows
            FROM load_log
            WHERE step = 'scraper'
            ORDER BY id DESC
            LIMIT ?
        )
        """,
        (payload_count,),
    ).fetchone()
    return row[0], row[1]


def log_etl(connection, candidate_count, updated_count):
    """Record the normalization result."""
    connection.execute(
        """
        INSERT INTO load_log
            (step, inserted_rows, skipped_rows, status, message)
        VALUES ('etl', ?, ?, 'OK', ?)
        """,
        (
            updated_count,
            candidate_count - updated_count,
            f"{updated_count} nombres normalizados de {candidate_count}",
        ),
    )


def count_expected_endpoints(connection):
    """Count expected table endpoints for both chambers."""
    return connection.execute(
        "SELECT COALESCE(SUM(table_count), 0) * 2 FROM polling_places"
    ).fetchone()[0]


def main():
    """Run ETL normalization steps."""
    connection = connect_database()
    try:
        endpoint_count = count_expected_endpoints(connection)
        party_count = count_parties(connection)
        candidate_count, updated_count = refresh_candidate_names(connection)
        inserted_count, skipped_count = collect_last_load(connection, endpoint_count)
        log_etl(connection, candidate_count, updated_count)
        connection.commit()
        print(
            f"endpoints={endpoint_count} parties={party_count} candidates={candidate_count} "
            f"normalized={updated_count} inserted={inserted_count} skipped={skipped_count}"
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
