-- 1) A posted document may go back to draft ("unpost") — that is the only change
--    allowed to it. Everything else about a posted document stays immutable.
--    Unposting / deleting is done by the Ledger, in an open period, with the full
--    document content written to the audit trail.
DROP TRIGGER documents_posted_no_update;
CREATE TRIGGER documents_posted_no_update BEFORE UPDATE ON documents
WHEN OLD.status = 'posted' AND NOT (
        NEW.status = 'draft'
    AND NEW.company_id = OLD.company_id
    AND NEW.number = OLD.number
    AND NEW.doc_date = OLD.doc_date
    AND NEW.memo = OLD.memo
    AND NEW.layer_id = OLD.layer_id
    AND NEW.reversal_of IS OLD.reversal_of
    AND NEW.created_at = OLD.created_at
)
BEGIN SELECT RAISE(ABORT, 'posted document is immutable'); END;

-- 2) Document numbers are never reused, even after a deletion.
ALTER TABLE companies ADD COLUMN last_number INTEGER NOT NULL DEFAULT 0;
UPDATE companies SET last_number = (
    SELECT COALESCE(MAX(number), 0) FROM documents WHERE documents.company_id = companies.id
);
