import json
import sqlite3
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "db" / "puestos_2026.db"
DATA_PATH = ROOT_DIR / "dashboard" / "data.json"
INDEX_PATH = ROOT_DIR / "dashboard" / "index.html"


def connect_database():
    """Open the SQLite database."""
    if not DB_PATH.exists():
        raise SystemExit("No existe db/puestos_2026.db. Ejecute primero scraper/scraper.py")
    return sqlite3.connect(DB_PATH)


def query_rows(connection, sql, params=()):
    """Return rows as dictionaries."""
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def load_export_data(connection):
    """Build the dashboard data payload."""
    municipalities = query_rows(
        connection,
        """
        SELECT 'BOYACA' AS department, m.name AS municipality, COALESCE(SUM(r.votes), 0) AS ca_votes
        FROM municipalities m
        LEFT JOIN results r
          ON r.municipality_id = m.id
         AND r.chamber = 'CA'
         AND r.candidate_id IS NULL
        GROUP BY m.id, m.name
        ORDER BY m.name
        """,
    )
    top_candidates = query_rows(
        connection,
        """
        SELECT
            'BOYACA' AS department,
            m.name AS municipality,
            r.chamber,
            c.candidate_name,
            p.party_name,
            p.party_code,
            COALESCE(p.color, '#666666') AS color,
            SUM(r.votes) AS votes
        FROM results r
        JOIN municipalities m ON m.id = r.municipality_id
        JOIN candidates c ON c.id = r.candidate_id
        JOIN parties p ON p.id = r.party_id
        WHERE r.chamber IN ('CA', 'SE')
          AND c.candidate_code <> '0'
        GROUP BY r.chamber, m.name, c.candidate_name, p.party_name, p.party_code, p.color
        ORDER BY r.chamber, m.name, votes DESC
        """,
    )
    party_totals = query_rows(
        connection,
        """
        SELECT
            'BOYACA' AS department,
            m.name AS municipality,
            r.chamber,
            p.party_name,
            p.party_code,
            COALESCE(p.color, '#666666') AS color,
            SUM(r.votes) AS votes
        FROM results r
        JOIN municipalities m ON m.id = r.municipality_id
        JOIN parties p ON p.id = r.party_id
        WHERE r.chamber IN ('CA', 'SE')
          AND r.candidate_id IS NULL
        GROUP BY r.chamber, m.name, p.party_name, p.party_code, p.color
        ORDER BY r.chamber, m.name, votes DESC
        """,
    )
    senate_leaders = query_rows(
        connection,
        """
        WITH totals AS (
            SELECT 'BOYACA' AS department, m.name AS municipality, p.party_name, p.party_code, SUM(r.votes) AS votes
            FROM results r
            JOIN municipalities m ON m.id = r.municipality_id
            JOIN parties p ON p.id = r.party_id
            WHERE r.chamber = 'SE'
              AND r.candidate_id IS NULL
            GROUP BY m.name, p.party_name, p.party_code
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY department, municipality ORDER BY votes DESC) AS rn
            FROM totals
        )
        SELECT department, municipality, party_name, party_code, votes
        FROM ranked
        WHERE rn = 1
        """,
    )
    green_ratio = query_rows(
        connection,
        """
        WITH ca AS (
            SELECT 'BOYACA' AS department, m.name AS municipality, pp.place_name, pp.place_code, SUM(r.votes) AS ca_votes
            FROM results r
            JOIN municipalities m ON m.id = r.municipality_id
            JOIN polling_places pp ON pp.id = r.polling_place_id
            JOIN parties p ON p.id = r.party_id
            WHERE r.chamber = 'CA'
              AND p.party_code = '5'
              AND r.candidate_id IS NULL
            GROUP BY m.name, pp.place_name, pp.place_code
        ),
        se AS (
            SELECT 'BOYACA' AS department, m.name AS municipality, pp.place_code, SUM(r.votes) AS se_votes
            FROM results r
            JOIN municipalities m ON m.id = r.municipality_id
            JOIN polling_places pp ON pp.id = r.polling_place_id
            JOIN parties p ON p.id = r.party_id
            WHERE r.chamber = 'SE'
              AND p.party_code = '57'
              AND r.candidate_id IS NULL
            GROUP BY m.name, pp.place_code
        )
        SELECT
            ca.municipality,
            ca.department,
            ca.place_name,
            ca.place_code,
            ca.ca_votes,
            COALESCE(se.se_votes, 0) AS se_votes,
            ROUND(COALESCE(se.se_votes, 0) * 1.0 / NULLIF(ca.ca_votes, 0), 3) AS ratio
        FROM ca
        LEFT JOIN se ON se.department = ca.department AND se.municipality = ca.municipality AND se.place_code = ca.place_code
        ORDER BY ca.municipality, ratio DESC
        """,
    )
    return {
        "municipalities": municipalities,
        "topCandidates": top_candidates,
        "partyTotals": party_totals,
        "senateLeaders": senate_leaders,
        "greenRatio": green_ratio,
    }


def update_embedded_data(payload):
    """Replace the embedded data block in index.html."""
    if not INDEX_PATH.exists():
        return
    html = INDEX_PATH.read_text(encoding="utf-8")
    start = "<script id=\"embedded-data\" type=\"application/json\">"
    end = "</script>"
    start_index = html.find(start)
    if start_index == -1:
        return
    data_start = start_index + len(start)
    data_end = html.find(end, data_start)
    if data_end == -1:
        return
    pretty = json.dumps(payload, ensure_ascii=False)
    updated = html[:data_start] + pretty + html[data_end:]
    INDEX_PATH.write_text(updated, encoding="utf-8")


def main():
    """Export dashboard data."""
    connection = connect_database()
    try:
        payload = load_export_data(connection)
        DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        update_embedded_data(payload)
        print(f"dashboard/data.json escrito con {len(payload['municipalities'])} municipios")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
