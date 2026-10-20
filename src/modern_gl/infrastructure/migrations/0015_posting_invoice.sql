-- The e-qaimə (electronic invoice of the tax portal) a posting belongs to: its number,
-- written as the portal shows it (upper case, no spaces). A purchase on 60, its ƏDV and
-- the payment carry the same number, so a report gathers them per invoice.

ALTER TABLE postings ADD COLUMN invoice TEXT
    CHECK (invoice IS NULL OR (TRIM(invoice) <> '' AND invoice = upper(invoice)));

CREATE INDEX postings_by_invoice ON postings (company_id, invoice) WHERE invoice IS NOT NULL;
