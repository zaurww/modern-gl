-- A purchase whose goods came before their e-qaimə (D119): posted now at the supplier's
-- price, its e-qaimə number (and VAT) written in when the e-qaimə comes — by hand or by
-- the import from the portal, which offers it the e-qaimə of the same supplier. Only a
-- purchase without a number waits.

ALTER TABLE inventory_documents ADD COLUMN awaits_invoice INTEGER NOT NULL DEFAULT 0
    CHECK (awaits_invoice IN (0, 1)
           AND (awaits_invoice = 0 OR (doc_type = 'receipt' AND invoice IS NULL)));

CREATE INDEX inventory_documents_awaiting
    ON inventory_documents (company_id, awaits_invoice, doc_date);
