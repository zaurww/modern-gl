-- The basis «Digər» (D-new-basis-other): a purchase or a sale made on a document that is
-- neither an e-qaimə nor a customs declaration — an act, a receipt, a contract. Its name
-- and number are free text, kept on the document only: no number goes onto the postings,
-- so it stays out of the portal reconciliation, the ƏDV and the unpaid e-qaimə.

ALTER TABLE inventory_documents ADD COLUMN basis_note TEXT
    CHECK (basis_note IS NULL OR (TRIM(basis_note) <> '' AND invoice IS NULL));

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
    AND NEW.incoming_reason IS OLD.incoming_reason
    AND NEW.basis_note IS OLD.basis_note
)
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
