-- Tax details of a counterparty. A resident has a VÖEN (10 digits, may be unknown);
-- a non-resident has no VÖEN but a country and a tax number of its own country
-- (EIN, VAT ID, TIN…), kept as typed. Both go to `tax_id`; `nonresident` says which.

ALTER TABLE subconto_values ADD COLUMN nonresident INTEGER NOT NULL DEFAULT 0
    CHECK (nonresident IN (0, 1));
ALTER TABLE subconto_values ADD COLUMN tax_id TEXT
    CHECK (tax_id IS NULL OR TRIM(tax_id) <> '');
ALTER TABLE subconto_values ADD COLUMN country TEXT
    CHECK (country IS NULL OR TRIM(country) <> '');

CREATE INDEX subconto_values_tax_id ON subconto_values (company_id, tax_id);
