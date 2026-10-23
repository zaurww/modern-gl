-- The company's own VÖEN (D111): what the tax portal is checked against before anything is
-- loaded from it — e-qaimə, the ƏDV deposit account. NULL: not known yet (the first sign-in
-- to the portal offers its VÖEN).

ALTER TABLE companies ADD COLUMN tax_id TEXT
    CHECK (tax_id IS NULL OR (length(tax_id) = 10 AND tax_id NOT GLOB '*[^0-9]*'));
