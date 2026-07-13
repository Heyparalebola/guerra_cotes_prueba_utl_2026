import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "db" / "puestos_2026.db"
OUTPUT_PATH = ROOT_DIR / "viz" / "scatter_ca_se.png"


def load_scatter_data():
    """Read CA and SE totals by table."""
    if not DB_PATH.exists():
        raise SystemExit("No existe db/puestos_2026.db. Ejecute primero scraper/scraper.py")
    query = """
    WITH totals AS (
        SELECT
            m.name AS municipality,
            pp.place_code,
            r.table_number,
            r.chamber,
            SUM(r.votes) AS votes
        FROM results r
        JOIN municipalities m ON m.id = r.municipality_id
        JOIN polling_places pp ON pp.id = r.polling_place_id
        WHERE r.candidate_id IS NULL
        GROUP BY m.name, pp.place_code, r.table_number, r.chamber
    )
    SELECT
        ca.municipality,
        ca.place_code,
        ca.table_number,
        ca.votes AS ca_votes,
        se.votes AS se_votes
    FROM totals ca
    JOIN totals se
      ON se.municipality = ca.municipality
     AND se.place_code = ca.place_code
     AND se.table_number = ca.table_number
     AND se.chamber = 'SE'
    WHERE ca.chamber = 'CA'
    """
    with sqlite3.connect(DB_PATH) as connection:
        return pd.read_sql_query(query, connection)


def calculate_stats(frame):
    """Calculate Pearson r and OLS slope."""
    if len(frame) < 2:
        raise SystemExit("No hay mesas suficientes para scatter CA vs SE")
    x = frame["ca_votes"].astype(float).to_numpy()
    y = frame["se_votes"].astype(float).to_numpy()
    slope, intercept = np.polyfit(x, y, 1)
    r_value = np.corrcoef(x, y)[0, 1]
    return float(r_value), float(slope), float(intercept)


def render_scatter(frame, r_value, slope, intercept):
    """Render the scatter plot image."""
    plt.figure(figsize=(9, 6))
    for municipality, group in frame.groupby("municipality"):
        plt.scatter(group["ca_votes"], group["se_votes"], label=municipality, alpha=0.75)
    x_values = np.linspace(frame["ca_votes"].min(), frame["ca_votes"].max(), 100)
    plt.plot(x_values, slope * x_values + intercept, color="#111111", linewidth=1.5)
    plt.title("Mesas: votos CA vs votos SE")
    plt.xlabel("Votos CA")
    plt.ylabel("Votos SE")
    plt.text(
        0.03,
        0.95,
        f"r={r_value:.3f} | pendiente={slope:.3f} | n_mesas={len(frame)}",
        transform=plt.gca().transAxes,
        va="top",
    )
    plt.legend()
    plt.tight_layout()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUTPUT_PATH, dpi=160)
    plt.close()


def main():
    """Build scatter_ca_se.png."""
    frame = load_scatter_data()
    r_value, slope, intercept = calculate_stats(frame)
    render_scatter(frame, r_value, slope, intercept)
    print(f"r={r_value:.3f} | pendiente={slope:.3f} | n_mesas={len(frame)}")


if __name__ == "__main__":
    main()
