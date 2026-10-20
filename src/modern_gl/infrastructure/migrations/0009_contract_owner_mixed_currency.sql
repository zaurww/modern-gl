-- 1) A directory may belong to another one, like a 1C "подчинённый справочник":
--    contracts belong to counterparties. A contract with an owner is offered and accepted
--    only next to that counterparty; one without an owner stays common to all.
-- 2) accounts.currency gets a third mode: 2 = in manat or in a currency (settlements
--    with local and foreign partners on one account 60 / 62).

ALTER TABLE subconto_kinds ADD COLUMN owner_kind_id INTEGER REFERENCES subconto_kinds(id);
ALTER TABLE subconto_values ADD COLUMN owner_id INTEGER REFERENCES subconto_values(id);

-- Added columns cannot carry composite foreign keys: keep companies apart by triggers.
CREATE TRIGGER subconto_kind_owner_company_insert BEFORE INSERT ON subconto_kinds
WHEN NEW.owner_kind_id IS NOT NULL
 AND (SELECT company_id FROM subconto_kinds WHERE id = NEW.owner_kind_id) IS NOT NEW.company_id
BEGIN SELECT RAISE(ABORT, 'owner directory belongs to another company'); END;

CREATE TRIGGER subconto_kind_owner_company_update BEFORE UPDATE OF owner_kind_id ON subconto_kinds
WHEN NEW.owner_kind_id IS NOT NULL
 AND (SELECT company_id FROM subconto_kinds WHERE id = NEW.owner_kind_id) IS NOT NEW.company_id
BEGIN SELECT RAISE(ABORT, 'owner directory belongs to another company'); END;

CREATE TRIGGER subconto_owner_company_insert BEFORE INSERT ON subconto_values
WHEN NEW.owner_id IS NOT NULL
 AND (SELECT company_id FROM subconto_values WHERE id = NEW.owner_id) IS NOT NEW.company_id
BEGIN SELECT RAISE(ABORT, 'owner belongs to another company'); END;

CREATE TRIGGER subconto_owner_company_update BEFORE UPDATE OF owner_id ON subconto_values
WHEN NEW.owner_id IS NOT NULL
 AND (SELECT company_id FROM subconto_values WHERE id = NEW.owner_id) IS NOT NEW.company_id
BEGIN SELECT RAISE(ABORT, 'owner belongs to another company'); END;

-- Contracts belong to counterparties (the standard directories of the templates).
UPDATE subconto_kinds
SET owner_kind_id = (
    SELECT o.id FROM subconto_kinds o
    WHERE o.company_id = subconto_kinds.company_id AND o.code = 'counterparty')
WHERE code = 'contract';

-- An existing contract used next to exactly one counterparty gets it as its owner;
-- contracts used with several counterparties (or never) stay common.
WITH owned AS (
    SELECT c.id AS contract_kind, c.owner_kind_id AS owner_kind
    FROM subconto_kinds c WHERE c.owner_kind_id IS NOT NULL
),
sides AS (
    SELECT debit_account_id AS account_id, dt_sc1 AS s1, dt_sc2 AS s2, dt_sc3 AS s3
    FROM postings
    UNION ALL
    SELECT credit_account_id, ct_sc1, ct_sc2, ct_sc3 FROM postings
),
pairs AS (
    SELECT
        CASE o.contract_kind
            WHEN a.sc1_kind_id THEN s.s1 WHEN a.sc2_kind_id THEN s.s2
            WHEN a.sc3_kind_id THEN s.s3 END AS contract_id,
        CASE o.owner_kind
            WHEN a.sc1_kind_id THEN s.s1 WHEN a.sc2_kind_id THEN s.s2
            WHEN a.sc3_kind_id THEN s.s3 END AS owner_id
    FROM sides s
    JOIN accounts a ON a.id = s.account_id
    JOIN owned o ON o.contract_kind IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
                AND o.owner_kind IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
),
single AS (
    SELECT contract_id, MIN(owner_id) AS owner_id FROM pairs
    WHERE contract_id IS NOT NULL AND owner_id IS NOT NULL
    GROUP BY contract_id
    HAVING COUNT(DISTINCT owner_id) = 1
)
UPDATE subconto_values
SET owner_id = (SELECT owner_id FROM single WHERE single.contract_id = subconto_values.id)
WHERE id IN (SELECT contract_id FROM single);

-- Settlements with suppliers and customers may be in a currency too (manat stays as is).
-- Not where a posting already carries the currency of its other side (Dt 60 / Ct 52 in
-- USD): those dollars would start counting on 60.
UPDATE accounts SET currency = 2
WHERE currency = 0 AND is_group = 0
  AND (code IN ('60', '62') OR code LIKE '60.%' OR code LIKE '62.%')
  AND NOT EXISTS (
      SELECT 1 FROM postings p
      WHERE p.currency_id IS NOT NULL
        AND accounts.id IN (p.debit_account_id, p.credit_account_id));
