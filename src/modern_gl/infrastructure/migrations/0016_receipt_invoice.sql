-- The basis of a warehouse receipt: an e-qaimə, or for imported goods a customs
-- declaration (gömrük bəyannaməsi). Its number goes onto the receipt's GL postings
-- (Dt inventory / Kt 60 and Dt input ƏDV / Kt 60), as postings.invoice (0015);
-- invoice_kind says which one it is: NULL an e-qaimə, 'customs' a declaration.

ALTER TABLE inventory_documents ADD COLUMN invoice TEXT
    CHECK (invoice IS NULL OR (TRIM(invoice) <> '' AND invoice = upper(invoice)));
ALTER TABLE inventory_documents ADD COLUMN invoice_kind TEXT
    CHECK (invoice_kind IS NULL OR (invoice_kind = 'customs' AND invoice IS NOT NULL));
ALTER TABLE postings ADD COLUMN invoice_kind TEXT
    CHECK (invoice_kind IS NULL OR (invoice_kind = 'customs' AND invoice IS NOT NULL));

DROP TRIGGER inventory_documents_posted_no_update;
CREATE TRIGGER inventory_documents_posted_no_update BEFORE UPDATE ON inventory_documents
WHEN OLD.status = 'posted' AND NOT (
        NEW.status = 'draft'
    AND NEW.company_id = OLD.company_id
    AND NEW.number = OLD.number
    AND NEW.doc_date = OLD.doc_date
    AND NEW.doc_type = OLD.doc_type
    AND NEW.memo = OLD.memo
    AND NEW.landed_cost_type_id IS OLD.landed_cost_type_id
    AND NEW.gl_document_id IS OLD.gl_document_id
    AND NEW.created_at = OLD.created_at
    AND NEW.vat_rate IS OLD.vat_rate
    AND NEW.allocation_method IS OLD.allocation_method
    AND NEW.currency_id IS OLD.currency_id
    AND NEW.currency_rate IS OLD.currency_rate
    AND NEW.invoice IS OLD.invoice
    AND NEW.invoice_kind IS OLD.invoice_kind
)
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
