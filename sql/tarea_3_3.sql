WITH ca_candidate_votes AS (
    SELECT
        r.municipality_id,
        r.polling_place_id,
        r.table_number,
        r.party_id,
        CASE p.party_code
            WHEN '5' THEN '57'
            WHEN '87' THEN '92'
            ELSE p.party_code
        END AS se_party_code,
        r.candidate_id,
        SUM(r.votes) AS candidate_ca_votes
    FROM results r
    JOIN parties p ON p.id = r.party_id
    JOIN candidates c ON c.id = r.candidate_id
    WHERE r.chamber = 'CA'
      AND r.candidate_id IS NOT NULL
      AND c.candidate_code <> '0'
    GROUP BY r.municipality_id, r.polling_place_id, r.table_number,
             r.party_id, se_party_code, r.candidate_id
),
ca_party_votes AS (
    SELECT
        r.municipality_id,
        r.polling_place_id,
        r.table_number,
        r.party_id,
        SUM(votes) AS party_ca_votes
    FROM results r
    WHERE r.chamber = 'CA'
      AND r.candidate_id IS NULL
    GROUP BY r.municipality_id, r.polling_place_id, r.table_number, r.party_id
),
se_party_votes AS (
    SELECT
        r.municipality_id,
        r.polling_place_id,
        r.table_number,
        p.party_code,
        SUM(r.votes) AS party_se_votes
    FROM results r
    JOIN parties p ON p.id = r.party_id
    WHERE r.chamber = 'SE'
      AND r.candidate_id IS NULL
    GROUP BY r.municipality_id, r.polling_place_id, r.table_number, p.party_code
),
attribution AS (
    SELECT
        ccv.municipality_id,
        ccv.polling_place_id,
        ccv.table_number,
        ccv.party_id,
        ccv.candidate_id,
        ccv.candidate_ca_votes,
        cpv.party_ca_votes,
        COALESCE(spv.party_se_votes, 0) AS party_se_votes,
        (ccv.candidate_ca_votes * 1.0 / NULLIF(cpv.party_ca_votes, 0))
            * COALESCE(spv.party_se_votes, 0) AS attributed_se_votes
    FROM ca_candidate_votes ccv
    JOIN ca_party_votes cpv
      ON cpv.municipality_id = ccv.municipality_id
     AND cpv.polling_place_id = ccv.polling_place_id
     AND cpv.table_number = ccv.table_number
     AND cpv.party_id = ccv.party_id
    LEFT JOIN se_party_votes spv
      ON spv.municipality_id = ccv.municipality_id
     AND spv.polling_place_id = ccv.polling_place_id
     AND spv.table_number = ccv.table_number
     AND spv.party_code = ccv.se_party_code
)
SELECT
    c.candidate_code,
    c.candidate_name,
    p.party_code,
    p.party_name,
    ROUND(SUM(a.attributed_se_votes), 2) AS attributed_se_votes,
    SUM(a.candidate_ca_votes) AS candidate_ca_votes,
    ROUND(SUM(a.party_se_votes), 2) AS party_se_votes_context,
    COUNT(DISTINCT a.municipality_id || '-' || a.polling_place_id || '-' || a.table_number) AS tables_used
FROM attribution a
JOIN candidates c ON c.id = a.candidate_id
JOIN parties p ON p.id = a.party_id
GROUP BY c.candidate_code, c.candidate_name, p.party_code, p.party_name
ORDER BY attributed_se_votes DESC
LIMIT 5;
