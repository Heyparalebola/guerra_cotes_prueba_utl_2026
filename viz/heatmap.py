import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "db" / "puestos_2026.db"
OUTPUT_PATH = ROOT_DIR / "viz" / "heatmap_municipios.png"


def load_heatmap_data():
    """Read top candidate shares by municipality."""
    if not DB_PATH.exists():
        raise SystemExit("No existe db/puestos_2026.db. Ejecute primero scraper/scraper.py")
    query = """
    WITH candidate_votes AS (
        SELECT
            c.id AS candidate_id,
            c.candidate_name,
            p.party_name,
            m.name AS municipality,
            SUM(r.votes) AS votes
        FROM results r
        JOIN candidates c ON c.id = r.candidate_id
        JOIN parties p ON p.id = r.party_id
        JOIN municipalities m ON m.id = r.municipality_id
        WHERE r.chamber = 'CA'
          AND c.candidate_code <> '0'
        GROUP BY c.id, c.candidate_name, p.party_name, m.name
    ),
    top_candidates AS (
        SELECT candidate_id, SUM(votes) AS total_votes
        FROM candidate_votes
        GROUP BY candidate_id
        ORDER BY total_votes DESC
        LIMIT 8
    ),
    municipality_totals AS (
        SELECT m.name AS municipality, SUM(r.votes) AS total_votes
        FROM results r
        JOIN municipalities m ON m.id = r.municipality_id
        WHERE r.chamber = 'CA'
          AND r.candidate_id IS NULL
        GROUP BY m.name
    )
    SELECT
        cv.candidate_name || ' - ' || cv.party_name AS candidate_name,
        cv.municipality,
        ROUND(cv.votes * 100.0 / NULLIF(mt.total_votes, 0), 2) AS share
    FROM candidate_votes cv
    JOIN top_candidates tc ON tc.candidate_id = cv.candidate_id
    JOIN municipality_totals mt ON mt.municipality = cv.municipality
    """
    with sqlite3.connect(DB_PATH) as connection:
        return pd.read_sql_query(query, connection)


def render_heatmap(frame):
    """Render the heatmap image."""
    if frame.empty:
        raise SystemExit("No hay datos CA suficientes para generar heatmap")
    matrix = frame.pivot_table(
        index="candidate_name",
        columns="municipality",
        values="share",
        fill_value=0,
    )
    figure, axis = plt.subplots(figsize=(10, 6))
    image = axis.imshow(matrix.values, cmap="YlGnBu", aspect="auto")
    axis.set_xticks(range(len(matrix.columns)))
    axis.set_xticklabels(matrix.columns, rotation=0)
    axis.set_yticks(range(len(matrix.index)))
    axis.set_yticklabels(matrix.index)
    for row_index in range(matrix.shape[0]):
        for column_index in range(matrix.shape[1]):
            value = matrix.values[row_index, column_index]
            axis.text(column_index, row_index, f"{value:.1f}", ha="center", va="center", fontsize=8)
    figure.colorbar(image, ax=axis, label="% del total municipal")
    axis.set_title("Top candidatos CA: porcentaje del total municipal")
    axis.set_xlabel("Municipio")
    axis.set_ylabel("Candidato")
    plt.tight_layout()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUTPUT_PATH, dpi=160)
    plt.close()


def main():
    """Build heatmap_municipios.png."""
    frame = load_heatmap_data()
    render_heatmap(frame)
    print(f"{OUTPUT_PATH} generado")


if __name__ == "__main__":
    main()
