-- Replace the Soviet-era account "kind" (active / passive / active-passive) with:
--   * the normal balance side, derived from account_class + contra (no column needed);
--   * two_sided: the balance may legitimately be on either side, so it is shown
--     expanded per first subconto (receivables and payables don't cancel out).

ALTER TABLE accounts ADD COLUMN two_sided INTEGER NOT NULL DEFAULT 0;
UPDATE accounts SET two_sided = 1 WHERE kind = 'AP';

-- Accounts still unclassified get the class their kind implied.
UPDATE accounts SET account_class = 'asset' WHERE account_class IS NULL AND kind = 'A';
UPDATE accounts SET account_class = 'liability' WHERE account_class IS NULL AND kind = 'P';

ALTER TABLE accounts DROP COLUMN kind;
