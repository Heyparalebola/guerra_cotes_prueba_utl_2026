PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS municipalities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS polling_places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_id INTEGER NOT NULL,
    place_code TEXT NOT NULL,
    place_name TEXT NOT NULL,
    zone_code TEXT,
    table_count INTEGER NOT NULL DEFAULT 0 CHECK (table_count >= 0),
    FOREIGN KEY (municipality_id) REFERENCES municipalities(id),
    UNIQUE (municipality_id, place_code)
);

CREATE TABLE IF NOT EXISTS parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_code TEXT NOT NULL UNIQUE,
    party_name TEXT NOT NULL,
    color TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_code TEXT NOT NULL,
    candidate_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    party_id INTEGER NOT NULL,
    chamber TEXT NOT NULL CHECK (chamber IN ('CA', 'SE')),
    FOREIGN KEY (party_id) REFERENCES parties(id),
    UNIQUE (candidate_code, party_id, chamber)
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_id INTEGER NOT NULL,
    polling_place_id INTEGER NOT NULL,
    table_number TEXT NOT NULL,
    chamber TEXT NOT NULL CHECK (chamber IN ('CA', 'SE')),
    party_id INTEGER NOT NULL,
    candidate_id INTEGER,
    votes INTEGER NOT NULL DEFAULT 0 CHECK (votes >= 0),
    source_path TEXT NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (municipality_id) REFERENCES municipalities(id),
    FOREIGN KEY (polling_place_id) REFERENCES polling_places(id),
    FOREIGN KEY (party_id) REFERENCES parties(id),
    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
);

CREATE TABLE IF NOT EXISTS raw_payloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_id INTEGER NOT NULL,
    chamber TEXT NOT NULL CHECK (chamber IN ('CA', 'SE')),
    source_path TEXT NOT NULL,
    payload TEXT NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (municipality_id) REFERENCES municipalities(id),
    UNIQUE (municipality_id, chamber, source_path)
);

CREATE TABLE IF NOT EXISTS load_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    step TEXT NOT NULL,
    municipality TEXT,
    chamber TEXT,
    inserted_rows INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_results_municipality_chamber
ON results (municipality_id, chamber);

CREATE INDEX IF NOT EXISTS idx_results_party_chamber
ON results (party_id, chamber);

CREATE INDEX IF NOT EXISTS idx_results_place_table
ON results (polling_place_id, table_number);

CREATE INDEX IF NOT EXISTS idx_candidates_party_chamber
ON candidates (party_id, chamber);

CREATE INDEX IF NOT EXISTS idx_polling_places_municipality
ON polling_places (municipality_id, place_code);

CREATE UNIQUE INDEX IF NOT EXISTS ux_results_identity
ON results (
    municipality_id,
    polling_place_id,
    table_number,
    chamber,
    party_id,
    COALESCE(candidate_id, -1)
);
