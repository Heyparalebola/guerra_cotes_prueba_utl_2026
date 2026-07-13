WITH party_table_votes AS (
    SELECT
        municipality_id,
        polling_place_id,
        table_number,
        chamber,
        party_id,
        SUM(votes) AS party_votes
    FROM results
    WHERE candidate_id IS NULL
    GROUP BY municipality_id, polling_place_id, table_number, chamber, party_id
),
candidate_table_votes AS (
    SELECT
        municipality_id,
        polling_place_id,
        table_number,
        chamber,
        party_id,
        candidate_id,
        SUM(votes) AS candidate_votes
    FROM results
    WHERE candidate_id IS NOT NULL
    GROUP BY municipality_id, polling_place_id, table_number, chamber, party_id, candidate_id
)
SELECT
    m.name AS municipality,
    pp.place_code,
    pp.place_name,
    ctv.table_number,
    ctv.chamber,
    p.party_code,
    p.party_name,
    c.candidate_code,
    c.candidate_name,
    ctv.candidate_votes,
    ptv.party_votes,
    ROUND(ctv.candidate_votes * 1.0 / NULLIF(ptv.party_votes, 0), 3) AS share_of_party
FROM candidate_table_votes ctv
JOIN party_table_votes ptv
  ON ptv.municipality_id = ctv.municipality_id
 AND ptv.polling_place_id = ctv.polling_place_id
 AND ptv.table_number = ctv.table_number
 AND ptv.chamber = ctv.chamber
 AND ptv.party_id = ctv.party_id
JOIN municipalities m ON m.id = ctv.municipality_id
JOIN polling_places pp ON pp.id = ctv.polling_place_id
JOIN parties p ON p.id = ctv.party_id
JOIN candidates c ON c.id = ctv.candidate_id
WHERE c.candidate_code <> '0'
  AND ctv.candidate_votes * 1.0 / NULLIF(ptv.party_votes, 0) > 0.60
ORDER BY share_of_party DESC, candidate_votes DESC;
