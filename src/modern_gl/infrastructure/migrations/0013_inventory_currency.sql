-- Receipts and batch charges in a currency (D33, stage 4). The rate is fixed on the
-- document (manat per one unit, in millionths: 1.7 = 1700000; it defaults to the rate of
-- the day and may be changed); the manat amounts are the currency amounts at that rate.
-- Columns added by ALTER cannot carry the composite FK: the application checks the
-- currency belongs to the company.

ALTER TABLE inventory_documents ADD COLUMN currency_id INTEGER;
ALTER TABLE inventory_documents ADD COLUMN currency_rate INTEGER
    CHECK (currency_rate IS NULL OR currency_rate > 0);
ALTER TABLE inventory_lines ADD COLUMN currency_amount INTEGER
    CHECK (currency_amount IS NULL OR currency_amount >= 0);

ALTER TABLE landed_cost_charges ADD COLUMN currency_id INTEGER;
ALTER TABLE landed_cost_charges ADD COLUMN currency_rate INTEGER
    CHECK (currency_rate IS NULL OR currency_rate > 0);
ALTER TABLE landed_cost_charges ADD COLUMN currency_amount INTEGER
    CHECK (currency_amount IS NULL OR currency_amount >= 0);

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
)
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
