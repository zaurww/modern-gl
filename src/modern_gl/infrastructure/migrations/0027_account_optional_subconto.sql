-- Subconto added to an account that already has postings (D59): the old postings have no
-- value there, so that position may stay empty (reports show «not given»), and documents
-- posted before can still be reposted. Bits of the positions: 1 = sc1, 2 = sc2, 4 = sc3.

ALTER TABLE accounts ADD COLUMN sc_optional INTEGER NOT NULL DEFAULT 0
    CHECK (sc_optional BETWEEN 0 AND 7);
