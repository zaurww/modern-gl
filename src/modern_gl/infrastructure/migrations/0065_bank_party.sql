-- The other side of a bank statement's line as the bank names it: its VÖEN and its name.
-- The bank's spelling is a hint, not the counterparty's name — the official one comes
-- from the tax portal with an e-qaimə. A line whose VÖEN the directory does not have
-- waits as a draft without a counterparty and keeps these two: the counterparty is found
-- by them once it is there, and the next line of the same sender finds it the same way.

ALTER TABLE bank_operations ADD COLUMN party_tin TEXT NOT NULL DEFAULT '';
ALTER TABLE bank_operations ADD COLUMN party_name TEXT NOT NULL DEFAULT '';

-- the counterparty a statement's sender was given last time, by its VÖEN
CREATE INDEX bank_operations_party_tin
    ON bank_operations (company_id, party_tin) WHERE party_tin <> '';
