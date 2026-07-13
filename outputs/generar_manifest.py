import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "db" / "puestos_2026.db"
OUTPUT_PATH = ROOT_DIR / "outputs" / "evaluation_manifest.json"

META = {
    "name": "Christian Andres Guerra",
    "email": "christianandresguerra@gmail.com",
    "repository": "git@github.com:Heyparalebola/guerra_cotes_prueba_utl_2026.git",
}

REQUIRED_FILES = [
    "README.md",
    "requirements.txt",
    "scraper/scraper.py",
    "db/schema.sql",
    "db/etl.py",
    "sql/tarea_3_1.sql",
    "sql/tarea_3_2.sql",
    "sql/tarea_3_3.sql",
    "dashboard/export_data.py",
    "dashboard/index.html",
    "dashboard/data.json",
    "viz/heatmap.py",
    "viz/scatter.py",
    "viz/heatmap_municipios.png",
    "viz/scatter_ca_se.png",
    "outputs/evaluation_manifest.example.json",
]


def connect_database():
    """Open the SQLite database."""
    if not DB_PATH.exists():
        raise SystemExit("No existe db/puestos_2026.db. Ejecute primero scraper/scraper.py")
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def run_sql_file(connection, path):
    """Execute a SQL file and return status."""
    sql = path.read_text(encoding="utf-8")
    try:
        rows = connection.execute(sql).fetchall()
        return {"status": "OK", "rows": len(rows), "preview": [dict(row) for row in rows[:5]]}
    except Exception as exc:
        return {"status": "ERROR", "message": str(exc)}


def collect_municipalities(connection):
    """Count rows and reporting units by municipality."""
    rows = connection.execute(
        """
        WITH result_stats AS (
            SELECT
                municipality_id,
                SUM(CASE WHEN chamber = 'CA' THEN 1 ELSE 0 END) AS ca_rows,
                SUM(CASE WHEN chamber = 'SE' THEN 1 ELSE 0 END) AS se_rows,
                COUNT(*) AS total_rows,
                COUNT(DISTINCT polling_place_id || ':' || table_number) AS reporting_units,
                COUNT(DISTINCT CASE
                    WHEN table_number <> 'TOTAL_PUESTO'
                    THEN polling_place_id || ':' || table_number
                END) AS tables_loaded
                ,COUNT(DISTINCT CASE
                    WHEN table_number <> 'TOTAL_PUESTO' AND chamber = 'CA'
                    THEN polling_place_id || ':' || table_number
                END) AS ca_tables_loaded
                ,COUNT(DISTINCT CASE
                    WHEN table_number <> 'TOTAL_PUESTO' AND chamber = 'SE'
                    THEN polling_place_id || ':' || table_number
                END) AS se_tables_loaded
            FROM results
            GROUP BY municipality_id
        ),
        place_stats AS (
            SELECT
                municipality_id,
                COUNT(*) AS polling_places,
                SUM(table_count) AS tables_expected
            FROM polling_places
            GROUP BY municipality_id
        )
        SELECT
            m.name,
            COALESCE(rs.ca_rows, 0) AS ca_rows,
            COALESCE(rs.se_rows, 0) AS se_rows,
            COALESCE(rs.total_rows, 0) AS total_rows,
            COALESCE(ps.polling_places, 0) AS polling_places,
            COALESCE(ps.tables_expected, 0) AS tables_expected,
            MIN(
                COALESCE(rs.ca_tables_loaded, 0),
                COALESCE(rs.se_tables_loaded, 0)
            ) AS tables_loaded,
            COALESCE(rs.reporting_units, 0) AS reporting_units
        FROM municipalities m
        LEFT JOIN result_stats rs ON rs.municipality_id = m.id
        LEFT JOIN place_stats ps ON ps.municipality_id = m.id
        ORDER BY m.name
        """
    ).fetchall()
    return {row["name"]: dict(row) for row in rows}


def collect_party_leaders(connection):
    """Find the leading SE party by municipality."""
    rows = connection.execute(
        """
        WITH totals AS (
            SELECT m.name, p.party_name, p.party_code, SUM(r.votes) AS votes
            FROM results r
            JOIN municipalities m ON m.id = r.municipality_id
            JOIN parties p ON p.id = r.party_id
            WHERE r.chamber = 'SE'
              AND r.candidate_id IS NULL
            GROUP BY m.name, p.party_name, p.party_code
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY name ORDER BY votes DESC) AS rn
            FROM totals
        )
        SELECT name, party_name, party_code, votes
        FROM ranked
        WHERE rn = 1
        """
    ).fetchall()
    return {row["name"]: dict(row) for row in rows}


def collect_files():
    """Check required output files."""
    files = {}
    for relative_path in REQUIRED_FILES:
        path = ROOT_DIR / relative_path
        files[relative_path] = {"exists": path.exists(), "bytes": path.stat().st_size if path.exists() else 0}
    files["db/puestos_2026.db"] = {
        "exists": DB_PATH.exists(),
        "bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "publish_as_release_asset": DB_PATH.exists() and DB_PATH.stat().st_size > 50 * 1024 * 1024,
    }
    return files


def collect_table_counts(connection):
    """Count rows in the project tables."""
    table_names = [
        "municipalities",
        "polling_places",
        "parties",
        "candidates",
        "results",
        "raw_payloads",
        "load_log",
    ]
    return {
        table_name: connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        for table_name in table_names
    }


def collect_data_quality(connection):
    """Check aggregate rows against candidate detail."""
    row = connection.execute(
        """
        WITH party AS (
            SELECT municipality_id, polling_place_id, chamber, party_id, SUM(votes) AS votes
            FROM results
            WHERE candidate_id IS NULL
            GROUP BY municipality_id, polling_place_id, chamber, party_id
        ),
        candidate AS (
            SELECT municipality_id, polling_place_id, chamber, party_id, SUM(votes) AS votes
            FROM results
            WHERE candidate_id IS NOT NULL
            GROUP BY municipality_id, polling_place_id, chamber, party_id
        )
        SELECT
            COUNT(*) AS compared_groups,
            SUM(CASE WHEN party.votes = candidate.votes THEN 1 ELSE 0 END) AS matching_groups
        FROM party
        JOIN candidate USING (municipality_id, polling_place_id, chamber, party_id)
        """
    ).fetchone()
    table_rows = connection.execute(
        "SELECT COUNT(*) FROM results WHERE table_number <> 'TOTAL_PUESTO'"
    ).fetchone()[0]
    return {
        "party_candidate_groups_compared": row[0],
        "party_candidate_groups_matching": row[1],
        "result_granularity": "table" if table_rows else "polling_place",
        "individual_table_rows": table_rows,
    }


def run_scatter_capture():
    """Run scatter.py and capture printed metrics."""
    script = ROOT_DIR / "viz" / "scatter.py"
    if not script.exists() or not DB_PATH.exists():
        return {"status": "SKIPPED"}
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        return {"status": "OK", "stdout": result.stdout.strip()}
    except subprocess.CalledProcessError as exc:
        return {"status": "ERROR", "stdout": exc.stdout.strip(), "stderr": exc.stderr.strip()}


def main():
    """Generate evaluation_manifest.json."""
    manifest = {"candidate": META, "files": collect_files()}
    connection = connect_database()
    try:
        manifest["municipalities"] = collect_municipalities(connection)
        manifest["table_counts"] = collect_table_counts(connection)
        manifest["data_quality"] = collect_data_quality(connection)
        manifest["senate_leaders"] = collect_party_leaders(connection)
        manifest["sql"] = {
            "tarea_3_1": run_sql_file(connection, ROOT_DIR / "sql" / "tarea_3_1.sql"),
            "tarea_3_2": run_sql_file(connection, ROOT_DIR / "sql" / "tarea_3_2.sql"),
            "tarea_3_3": run_sql_file(connection, ROOT_DIR / "sql" / "tarea_3_3.sql"),
        }
    finally:
        connection.close()
    manifest["scatter"] = run_scatter_capture()
    manifest["files"] = collect_files()
    OUTPUT_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    complete = sum(
        1
        for item in manifest["municipalities"].values()
        if item.get("ca_rows", 0) > 0 and item.get("se_rows", 0) > 0
    )
    print(f"{complete}/4 municipios")
    expected_tables = sum(item["tables_expected"] for item in manifest["municipalities"].values())
    loaded_tables = sum(item["tables_loaded"] for item in manifest["municipalities"].values())
    print(f"mesas esperadas={expected_tables} con resultado individual={loaded_tables}")
    for name, result in manifest["sql"].items():
        print(f"{name}: {result['status']}")
    print(f"manifest: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
