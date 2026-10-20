-- A counterparty's official name as the tax portal writes it (e-qaimə), apart from the
-- name the company uses (`name`, often shorter). The VÖEN identifies the counterparty;
-- a new official name for the same VÖEN means it was renamed: the import asks (D45).

ALTER TABLE subconto_values ADD COLUMN legal_name TEXT
    CHECK (legal_name IS NULL OR TRIM(legal_name) <> '');
