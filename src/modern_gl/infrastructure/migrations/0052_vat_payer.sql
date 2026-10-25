-- The ƏDV module (stage 4 of the ƏDV declaration):
-- a company is a payer of ƏDV from a day: before it, no ƏDV is owed on sales nor credited
-- on purchases. NULL: a payer all along (as before).
ALTER TABLE companies ADD COLUMN vat_payer_from TEXT
    CHECK (vat_payer_from IS NULL
           OR vat_payer_from GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]');
-- A payment from a bank account straight to the supplier's ƏDV deposit account pays the
-- ƏDV, not the value (Tax Code 175): the posting and the bank operation line say so.
ALTER TABLE postings ADD COLUMN pays_vat INTEGER NOT NULL DEFAULT 0
    CHECK (pays_vat IN (0, 1));
ALTER TABLE bank_operation_lines ADD COLUMN pays_vat INTEGER NOT NULL DEFAULT 0
    CHECK (pays_vat IN (0, 1));
