-- Account roles: the accounts a company's automatic postings use, set by the user
-- instead of being found by a hard-coded code (D33). The first role: input VAT
-- (ƏDV к возмещению), debited by a warehouse receipt.

CREATE TABLE account_roles (
    company_id INTEGER NOT NULL REFERENCES companies(id),
    role       TEXT NOT NULL CHECK (TRIM(role) <> ''),
    account_id INTEGER NOT NULL,
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    PRIMARY KEY (company_id, role)
);

-- Existing companies: the chart templates keep input VAT on 19 (classic) or 19.3 (1C 7.7).
INSERT INTO account_roles (company_id, role, account_id)
SELECT company_id, 'input_vat', id FROM accounts a
WHERE is_group = 0 AND active = 1 AND code IN ('19', '19.3')
  AND NOT EXISTS (
      SELECT 1 FROM accounts b
      WHERE b.company_id = a.company_id AND b.code = '19' AND b.is_group = 0
        AND a.code = '19.3'
  );

-- A receipt's VAT: the rate of the document in hundredths of a percent (1800 = 18%,
-- NULL = without VAT) and each line's VAT in minor units; the line amount is without VAT.
ALTER TABLE inventory_documents ADD COLUMN vat_rate INTEGER
    CHECK (vat_rate IS NULL OR vat_rate BETWEEN 0 AND 10000);
ALTER TABLE inventory_lines ADD COLUMN vat_amount INTEGER NOT NULL DEFAULT 0
    CHECK (vat_amount >= 0);

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
)
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
