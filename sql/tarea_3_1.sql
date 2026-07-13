WITH ca_green AS (
    SELECT
        m.name AS municipality,
        pp.place_name,
        pp.place_code,
        SUM(r.votes) AS ca_votes
    FROM results r
    JOIN municipalities m ON m.id = r.municipality_id
    JOIN polling_places pp ON pp.id = r.polling_place_id
    JOIN parties p ON p.id = r.party_id
    WHERE r.chamber = 'CA'
      AND p.party_code = '5'
      AND r.candidate_id IS NULL
    GROUP BY m.name, pp.place_name, pp.place_code
),
se_green AS (
    SELECT
        m.name AS municipality,
        pp.place_code,
        SUM(r.votes) AS se_votes
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
    ca.place_code,
    ca.place_name,
    ca.ca_votes,
    COALESCE(se.se_votes, 0) AS se_votes,
    ROUND(COALESCE(se.se_votes, 0) * 1.0 / NULLIF(ca.ca_votes, 0), 3) AS green_ratio
FROM ca_green ca
LEFT JOIN se_green se
  ON se.municipality = ca.municipality
 AND se.place_code = ca.place_code
ORDER BY ca.municipality, green_ratio DESC;
