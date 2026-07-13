import argparse
import json
import sqlite3
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import get_close_matches
from pathlib import Path

import requests


BASE_URL = "https://resultadospreccongreso2026.registraduria.gov.co"
ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "db" / "puestos_2026.db"
SCHEMA_PATH = ROOT_DIR / "db" / "schema.sql"
SAMPLE_DIR = ROOT_DIR / "sample_data"

DEFAULT_MUNICIPALITIES = {
    "TUNJA": {"id": 1135, "code": "0700001", "slug": "TUNJA"},
    "PAIPA": {"id": 731, "code": "0700181", "slug": "PAIPA"},
    "SOGAMOSO": {"id": 1040, "code": "0700277", "slug": "SOGAMOSO"},
    "DUITAMA": {"id": 340, "code": "0700079", "slug": "DUITAMA"},
}

NOMENCLATOR_PATH = "/json/nomenclator.json"

PARTY_COLORS = {
    "5": ("ALIANZA VERDE", "#007C34"),
    "57": ("ALIANZA VERDE", "#007C34"),
    "87": ("PACTO HISTORICO", "#7B2D8B"),
    "92": ("PACTO HISTORICO", "#7B2D8B"),
    "10": ("CENTRO DEMOCRATICO", "#1E477D"),
    "2": ("CONSERVADOR", "#E07B00"),
}

ALIASES = {
    "votes": ("votes", "votos", "vot", "v", "total", "cantidad", "valor"),
    "party_code": ("party_code", "codpar", "cod_par", "codigo_partido", "cp", "par"),
    "party_name": ("party_name", "party", "partido", "nombre_partido", "nompar"),
    "candidate_code": ("candidate_code", "codcan", "cod_candidato", "codigo_candidato", "cc"),
    "candidate_name": ("candidate_name", "candidate", "candidato", "nombre_candidato", "nomcan"),
    "place_code": ("place_code", "codpuesto", "cod_puesto", "codigo_puesto", "puesto", "pue"),
    "place_name": ("place_name", "puesto_name", "nombre_puesto", "nompuesto", "puesto_nombre"),
    "table_number": ("table_number", "mesa", "numero_mesa", "nummesa", "table"),
    "table_count": ("table_count", "mesas"),
}

PARTY_CODE_ALIASES = (
    "party_code",
    "codpar",
    "cod_par",
    "codigo_partido",
    "codigo_partido_politico",
    "party_id",
)

PARTY_NAME_ALIASES = (
    "party_name",
    "nombre_partido",
    "nombre_partido_politico",
    "nompar",
)

PARTY_COLLECTION_KEYS = {
    "party",
    "parties",
    "partido",
    "partidos",
    "partidos_politicos",
    "partidospoliticos",
    "political_parties",
}


def parse_args():
    """Parse command line options."""
    parser = argparse.ArgumentParser(description="Scraper electoral Boyaca 2026")
    parser.add_argument("--municipios", nargs="+", help="Municipios a descargar")
    parser.add_argument("--preflight", action="store_true", help="Muestra rutas y disponibilidad")
    parser.add_argument("--workers", type=int, default=12, help="Descargas simultaneas")
    return parser.parse_args()


def normalize_text(value):
    """Return uppercase ASCII text."""
    if value is None:
        return ""
    raw = unicodedata.normalize("NFKD", str(value))
    clean = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return " ".join(clean.upper().split())


def connect_database():
    """Open the SQLite database and apply schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    with SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
        connection.executescript(schema_file.read())
    columns = {row[1] for row in connection.execute("PRAGMA table_info(polling_places)")}
    if "table_count" not in columns:
        connection.execute(
            "ALTER TABLE polling_places ADD COLUMN table_count INTEGER NOT NULL DEFAULT 0"
        )
    index_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'ux_results_identity'"
    ).fetchone()
    if index_row and "source_path" in (index_row[0] or ""):
        connection.execute("DROP INDEX ux_results_identity")
        connection.execute(
            """
            CREATE UNIQUE INDEX ux_results_identity
            ON results (
                municipality_id, polling_place_id, table_number,
                chamber, party_id, COALESCE(candidate_id, -1)
            )
            """
        )
    return connection


def request_json(path, retries=3, wait_seconds=1.5):
    """Fetch a JSON document with retry/backoff."""
    url = f"{BASE_URL}{path}"
    headers = {
        "Accept": "application/json",
        "Referer": f"{BASE_URL}/",
        "User-Agent": "utl-boyaca-2026-scraper/1.0",
    }
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "json" not in content_type and not response.text.lstrip().startswith(("{", "[")):
                raise ValueError("response is not JSON")
            return response.json()
        except Exception as exc:
            if attempt == retries:
                raise RuntimeError(f"{path}: {exc}") from exc
            time.sleep(wait_seconds * attempt)
    return None


def load_sample_payload(municipality, chamber):
    """Read a local sample payload when it exists."""
    names = [
        f"{municipality}_{chamber}.json",
        f"{municipality.lower()}_{chamber.lower()}.json",
        f"{chamber}_{municipality}.json",
        f"{chamber.lower()}_{municipality.lower()}.json",
    ]
    for file_name in names:
        sample_path = SAMPLE_DIR / file_name
        if sample_path.exists():
            with sample_path.open("r", encoding="utf-8") as sample_file:
                return json.load(sample_file), f"sample_data/{file_name}"
    return None, None


def build_municipality_catalog(nomenclator):
    """Build the Boyaca municipality lookup."""
    scopes = nomenclator["amb"][0]["ambitos"]
    catalog = {}
    for scope in scopes:
        code = str(scope.get("c") or "")
        if scope.get("l") != 3 or not code.startswith("07"):
            continue
        name = normalize_text(scope.get("n"))
        item = {
            "id": scope["i"],
            "code": code,
            "slug": scope.get("s") or name.replace(" ", "-"),
            "name": name,
        }
        catalog[name] = item
        catalog[normalize_text(str(item["slug"]).replace("-", " "))] = item
    return catalog


def get_target_municipalities(names, nomenclator):
    """Build the selected municipality list."""
    if not names:
        return [
            {**item, "name": name}
            for name, item in DEFAULT_MUNICIPALITIES.items()
        ]

    catalog = build_municipality_catalog(nomenclator)
    municipalities = []
    for raw_name in names:
        name = normalize_text(str(raw_name).replace("_", " ").replace("-", " "))
        item = catalog.get(name)
        if item is None:
            suggestions = get_close_matches(name, sorted(catalog), n=3, cutoff=0.6)
            hint = f". Sugerencias: {', '.join(suggestions)}" if suggestions else ""
            raise SystemExit(f"Municipio de Boyaca no encontrado: {raw_name}{hint}")
        if item not in municipalities:
            municipalities.append(item.copy())
    return municipalities


def register_municipality(connection, municipality):
    """Insert a municipality row."""
    connection.execute(
        """
        INSERT OR IGNORE INTO municipalities (id, name, code, slug)
        VALUES (?, ?, ?, ?)
        """,
        (municipality["id"], municipality["name"], municipality["code"], municipality["slug"]),
    )


def get_value(record, aliases):
    """Return the first matching value from a record."""
    lowered = {str(key).lower(): value for key, value in record.items()}
    for alias in aliases:
        if alias.lower() in lowered and lowered[alias.lower()] not in (None, ""):
            return lowered[alias.lower()]
    return None


def to_int(value):
    """Convert a loose vote value to int."""
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return None


def merge_context(context, record):
    """Carry parent fields into nested vote rows."""
    merged = dict(context)
    for field, aliases in ALIASES.items():
        value = get_value(record, aliases)
        if value not in (None, ""):
            merged[field] = value
    return merged


def extract_party_catalog(payload):
    """Extract the ACT party-index/name map from the public nomenclator."""
    catalog = {}

    if isinstance(payload, dict) and isinstance(payload.get("partidos"), list):
        for party in payload["partidos"]:
            if not isinstance(party, dict):
                continue
            party_index = party.get("i")
            party_name = party.get("nombre")
            if party_index not in (None, "") and party_name not in (None, ""):
                code = str(party_index).strip()
                catalog[code] = (
                    normalize_text(party_name),
                    party.get("color"),
                )
        return catalog

    def visit(node, party_context=False):
        if isinstance(node, dict):
            keys = {str(key).lower().replace("-", "_") for key in node}
            is_party_context = party_context

            party_code = get_value(node, PARTY_CODE_ALIASES)
            party_name = get_value(node, PARTY_NAME_ALIASES)

            # Some versions of the public config use generic c/n or id/name
            # fields inside a party collection. Do not apply those aliases to
            # the complete config because it also contains geographic data.
            if is_party_context:
                party_code = party_code or get_value(node, ("codigo", "code", "c", "id"))
                party_name = party_name or get_value(node, ("nombre", "name", "n"))

            if party_code not in (None, "") and party_name not in (None, ""):
                code = str(party_code).strip()
                name = normalize_text(party_name)
                if code and name and any(char.isdigit() for char in code):
                    catalog[code] = (name, None)

            for key, value in node.items():
                child_context = is_party_context or (
                    str(key).lower().replace("-", "_") in PARTY_COLLECTION_KEYS
                )
                visit(value, child_context)
        elif isinstance(node, list):
            for item in node:
                visit(item, party_context)

    visit(payload)
    return catalog


def load_party_catalog(nomenclator):
    """Build the party catalog from the nomenclator and retain fallbacks."""
    catalog = {
        code: (name, color)
        for code, (name, color) in PARTY_COLORS.items()
    }
    official_catalog = extract_party_catalog(nomenclator)
    for code, (name, color) in official_catalog.items():
        if code not in PARTY_COLORS:
            catalog[code] = (name, color)
    print(f"Catalogo de partidos cargado: {len(catalog)} codigos", file=sys.stderr)
    return catalog


def extract_rows(payload, chamber, defaults=None, party_catalog=None):
    """Extract vote rows from a flexible JSON shape."""
    official_rows = extract_official_rows(
        payload, chamber, defaults or {}, party_catalog=party_catalog
    )
    if official_rows is not None:
        return official_rows

    rows = []

    def walk(node, context):
        """Traverse a fallback JSON structure."""
        if isinstance(node, dict):
            merged = merge_context(context, node)
            votes = to_int(get_value(node, ALIASES["votes"]))
            party_code = merged.get("party_code")
            if votes is not None and party_code is not None:
                rows.append(build_row(merged, chamber, votes, party_catalog=party_catalog))
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value, merged)
        elif isinstance(node, list):
            for item in node:
                walk(item, context)

    walk(payload, defaults or {})
    return rows


def extract_official_rows(payload, chamber, defaults, party_catalog=None):
    """Parse the official ACT result structure."""
    if not isinstance(payload, dict) or not isinstance(payload.get("camaras"), list):
        return None

    rows = []
    for chamber_block in payload["camaras"]:
        for party_block in chamber_block.get("partotabla", []):
            party = party_block.get("act", party_block)
            party_code = party.get("codpar")
            party_votes = to_int(party.get("vot"))
            if party_code in (None, "") or party_votes is None:
                continue

            party_context = dict(defaults)
            party_context.update({
                "party_code": party_code,
                "party_name": None,
            })
            rows.append(build_row(party_context, chamber, party_votes, party_catalog=party_catalog))

            for candidate in party.get("cantotabla", []):
                candidate_votes = to_int(candidate.get("vot"))
                candidate_code = candidate.get("codcan")
                if candidate_votes is None or candidate_code in (None, ""):
                    continue
                full_name = " ".join(
                    str(candidate.get(field) or "").strip()
                    for field in ("nomcan", "nomcan2", "apecan", "apecan2")
                )
                candidate_context = dict(party_context)
                candidate_context.update({
                    "candidate_code": candidate_code,
                    "candidate_name": full_name,
                })
                rows.append(
                    build_row(candidate_context, chamber, candidate_votes, party_catalog=party_catalog)
                )
    return rows


def build_row(context, chamber, votes, party_catalog=None):
    """Create a normalized result row."""
    party_code = str(context.get("party_code")).strip()
    party_catalog = party_catalog or PARTY_COLORS
    default_party = party_catalog.get(party_code, (f"PARTIDO {party_code}", None))
    party_name = normalize_text(context.get("party_name") or default_party[0])
    candidate_code = context.get("candidate_code")
    candidate_name = normalize_text(context.get("candidate_name") or "")
    place_code = str(context.get("place_code") or "SIN_PUESTO").strip()
    place_name = normalize_text(context.get("place_name") or place_code)
    table_number = str(context.get("table_number") or "SIN_MESA").strip()
    return {
        "chamber": chamber,
        "party_code": party_code,
        "party_name": party_name,
        "party_color": default_party[1],
        "candidate_code": str(candidate_code).strip() if candidate_code not in (None, "") else None,
        "candidate_name": candidate_name,
        "place_code": place_code,
        "place_name": place_name,
        "table_number": table_number,
        "table_count": to_int(context.get("table_count")) or 0,
        "votes": votes,
    }


def save_raw_payload(connection, municipality, chamber, source_path, payload):
    """Store the source JSON once per run target."""
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO raw_payloads (municipality_id, chamber, source_path, payload)
        VALUES (?, ?, ?, ?)
        """,
        (municipality["id"], chamber, source_path, json.dumps(payload, ensure_ascii=False)),
    )
    return cursor.rowcount


def upsert_party(connection, row):
    """Insert a party and return its id."""
    connection.execute(
        """
        INSERT INTO parties (party_code, party_name, color)
        VALUES (?, ?, ?)
        ON CONFLICT (party_code) DO UPDATE SET
            party_name = excluded.party_name,
            color = COALESCE(excluded.color, parties.color)
        """,
        (row["party_code"], row["party_name"], row["party_color"]),
    )
    return connection.execute(
        "SELECT id FROM parties WHERE party_code = ?",
        (row["party_code"],),
    ).fetchone()[0]


def upsert_polling_place(connection, municipality_id, row):
    """Insert a polling place and return its id."""
    connection.execute(
        """
        INSERT INTO polling_places
            (municipality_id, place_code, place_name, table_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (municipality_id, place_code) DO UPDATE SET
            place_name = excluded.place_name,
            table_count = excluded.table_count
        """,
        (
            municipality_id,
            row["place_code"],
            row["place_name"],
            row["table_count"],
        ),
    )
    return connection.execute(
        """
        SELECT id FROM polling_places
        WHERE municipality_id = ? AND place_code = ?
        """,
        (municipality_id, row["place_code"]),
    ).fetchone()[0]


def upsert_candidate(connection, row, party_id):
    """Insert a candidate and return its id."""
    if not row["candidate_code"]:
        return None
    name = row["candidate_name"] or f"CANDIDATO {row['candidate_code']}"
    connection.execute(
        """
        INSERT INTO candidates
            (candidate_code, candidate_name, normalized_name, party_id, chamber)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (candidate_code, party_id, chamber) DO UPDATE SET
            candidate_name = excluded.candidate_name,
            normalized_name = excluded.normalized_name
        """,
        (row["candidate_code"], name, normalize_text(name), party_id, row["chamber"]),
    )
    return connection.execute(
        """
        SELECT id FROM candidates
        WHERE candidate_code = ? AND party_id = ? AND chamber = ?
        """,
        (row["candidate_code"], party_id, row["chamber"]),
    ).fetchone()[0]


def load_reference_cache(connection):
    """Load stable database identifiers into memory."""
    return {
        "parties": {
            row[0]: row[1]
            for row in connection.execute("SELECT party_code, id FROM parties")
        },
        "places": {
            (row[0], row[1]): row[2]
            for row in connection.execute(
                "SELECT municipality_id, place_code, id FROM polling_places"
            )
        },
        "candidates": {
            (row[0], row[1], row[2]): row[3]
            for row in connection.execute(
                "SELECT candidate_code, party_id, chamber, id FROM candidates"
            )
        },
    }


def insert_results(connection, municipality, rows, source_path, cache):
    """Insert parsed result rows idempotently."""
    values = []
    for row in rows:
        party_id = cache["parties"].get(row["party_code"])
        if party_id is None:
            party_id = upsert_party(connection, row)
            cache["parties"][row["party_code"]] = party_id

        place_key = (municipality["id"], row["place_code"])
        place_id = cache["places"].get(place_key)
        if place_id is None:
            place_id = upsert_polling_place(connection, municipality["id"], row)
            cache["places"][place_key] = place_id

        candidate_id = None
        if row["candidate_code"]:
            candidate_key = (row["candidate_code"], party_id, row["chamber"])
            candidate_id = cache["candidates"].get(candidate_key)
            if candidate_id is None:
                candidate_id = upsert_candidate(connection, row, party_id)
                cache["candidates"][candidate_key] = candidate_id

        values.append(
            (
                municipality["id"], place_id, row["table_number"], row["chamber"],
                party_id, candidate_id, row["votes"], source_path,
            )
        )

    before = connection.total_changes
    connection.executemany(
        """
        INSERT OR IGNORE INTO results
            (municipality_id, polling_place_id, table_number, chamber,
             party_id, candidate_id, votes, source_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    inserted = connection.total_changes - before
    return inserted, len(values) - inserted


def log_load(connection, step, municipality, chamber, inserted, skipped, status, message):
    """Write a compact load log row."""
    connection.execute(
        """
        INSERT INTO load_log
            (step, municipality, chamber, inserted_rows, skipped_rows, status, message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (step, municipality, chamber, inserted, skipped, status, message),
    )


def load_nomenclator():
    """Download the electoral nomenclator."""
    return request_json(NOMENCLATOR_PATH)


def collect_polling_places(nomenclator, municipality):
    """Return polling places for a municipality."""
    scopes = nomenclator["amb"][0]["ambitos"]
    by_index = {item["i"]: item for item in scopes}
    root = next(
        item for item in scopes
        if item.get("l") == 3 and item.get("c") == municipality["code"]
    )
    places = []

    def walk(scope):
        """Traverse municipality scopes to polling places."""
        if scope.get("l") == 6:
            places.append({
                "place_code": scope.get("c"),
                "place_name": normalize_text(scope.get("n")),
                "zone_code": str(scope.get("c", ""))[:8],
                "table_count": to_int(scope.get("m")) or 0,
            })
            return
        for child_group in scope.get("h", []):
            for child_index in child_group.get("p", []):
                walk(by_index[child_index])

    walk(root)
    return places


def fetch_payload(municipality, chamber, place=None):
    """Download official data or use an existing sample file."""
    if place:
        official_paths = [f"/json/ACT/{chamber}/{place['place_code']}.json"]
    else:
        official_paths = [
            f"/json/ACT/{chamber}/{municipality['id']}.json",
            f"/json/ACT/{chamber}/{municipality['code']}.json",
        ]
    errors = []
    for path in official_paths:
        try:
            return request_json(path), path
        except RuntimeError as exc:
            errors.append(str(exc))

    payload, source_path = load_sample_payload(municipality["name"], chamber)
    if payload is not None:
        return payload, source_path
    raise RuntimeError(" | ".join(errors))


def fetch_table_payload(place, chamber, table_number):
    """Download one table result payload."""
    scope_code = f"{place['place_code']}{table_number:06d}"
    source_path = f"/json/ACT/{chamber}/{scope_code}.json"
    return place, table_number, request_json(source_path), source_path


def chunked(items, size):
    """Yield fixed-size lists from a sequence."""
    for start in range(0, len(items), size):
        yield items[start:start + size]


def run_preflight(municipalities, nomenclator):
    """Print expected endpoints without writing data."""
    print("Municipios objetivo:")
    for municipality in municipalities:
        places = collect_polling_places(nomenclator, municipality)
        table_count = sum(place["table_count"] for place in places)
        print(
            f"- {municipality['name']}: codigo={municipality['code']} "
            f"indice={municipality['id']} puestos={len(places)} mesas={table_count}"
        )
        for chamber in ("CA", "SE"):
            print(
                f"  {chamber}: mesas_esperadas={table_count} "
                f"patron=/json/ACT/{chamber}/{{codigo_puesto}}{{mesa:06d}}.json"
            )


def run_scraper(municipalities, workers, nomenclator, party_catalog=None):
    """Download and store data for selected municipalities."""
    connection = connect_database()
    try:
        for municipality in municipalities:
            register_municipality(connection, municipality)
        connection.commit()
        cache = load_reference_cache(connection)

        for municipality in municipalities:
            places = collect_polling_places(nomenclator, municipality)
            for place in places:
                place_id = upsert_polling_place(connection, municipality["id"], place)
                cache["places"][(municipality["id"], place["place_code"])] = place_id
            connection.commit()

            for chamber in ("CA", "SE"):
                connection.execute(
                    """
                    DELETE FROM results
                    WHERE municipality_id = ? AND chamber = ?
                      AND table_number = 'TOTAL_PUESTO'
                    """,
                    (municipality["id"], chamber),
                )
                connection.execute(
                    "DELETE FROM raw_payloads WHERE municipality_id = ? AND chamber = ?",
                    (municipality["id"], chamber),
                )
                connection.commit()

                chamber_inserted = 0
                chamber_skipped = 0
                chamber_errors = 0
                processed = 0
                targets = [
                    (place, table_number)
                    for place in places
                    for table_number in range(1, place["table_count"] + 1)
                ]

                with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
                    for batch in chunked(targets, 48):
                        futures = [
                            executor.submit(fetch_table_payload, place, chamber, table_number)
                            for place, table_number in batch
                        ]
                        for future in as_completed(futures):
                            try:
                                place, table_number, payload, source_path = future.result()
                                rows = extract_rows(payload, chamber, {
                                    "place_code": place["place_code"],
                                    "place_name": place["place_name"],
                                    "table_number": str(table_number),
                                    "table_count": place["table_count"],
                                }, party_catalog=party_catalog)
                                inserted, skipped = insert_results(
                                    connection, municipality, rows, source_path, cache
                                )
                                chamber_inserted += inserted
                                chamber_skipped += skipped
                                status = "OK" if rows else "EMPTY"
                                message = f"{len(rows)} filas parseadas desde {source_path}"
                                log_load(
                                    connection, "scraper", municipality["name"], chamber,
                                    inserted, skipped, status, message,
                                )
                            except Exception as exc:
                                chamber_errors += 1
                                log_load(
                                    connection, "scraper", municipality["name"], chamber,
                                    0, 0, "ERROR", str(exc),
                                )
                            processed += 1
                        connection.commit()
                        if processed % 96 == 0 or processed == len(targets):
                            print(
                                f"{municipality['name']} {chamber}: "
                                f"mesas={processed}/{len(targets)} errores={chamber_errors}"
                            )

                status = "OK" if chamber_errors == 0 else "PARTIAL"
                print(
                    f"{municipality['name']} {chamber}: {status} "
                    f"mesas={len(targets) - chamber_errors}/{len(targets)} "
                    f"inserted={chamber_inserted} skipped={chamber_skipped}"
                )
    finally:
        connection.close()


def main():
    """Run the scraper CLI."""
    args = parse_args()
    nomenclator = load_nomenclator()
    municipalities = get_target_municipalities(args.municipios, nomenclator)
    if args.preflight:
        run_preflight(municipalities, nomenclator)
        return
    party_catalog = load_party_catalog(nomenclator)
    run_scraper(municipalities, args.workers, nomenclator, party_catalog)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Interrumpido")
