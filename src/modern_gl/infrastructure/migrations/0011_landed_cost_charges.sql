-- «Расходы по партии» (D33): a landed cost document has several expense lines (charges)
-- allocated over the receipt lines of a batch (its inventory_lines). A charge is typed in
-- the document (the broker's account, amount, VAT) or is an existing GL posting whose
-- debit is moved to stock (source_document_id + source_line_no; account and subconto are
-- copied from its debit side).

ALTER TABLE inventory_documents ADD COLUMN allocation_method TEXT
    CHECK (allocation_method IS NULL OR allocation_method IN ('value', 'quantity', 'manual'));

CREATE TABLE landed_cost_charges (
    id                 INTEGER PRIMARY KEY,
    company_id         INTEGER NOT NULL,
    document_id        INTEGER NOT NULL,
    line_no            INTEGER NOT NULL,
    cost_type_id       INTEGER,
    account_id         INTEGER,
    sc1                INTEGER,
    sc2                INTEGER,
    sc3                INTEGER,
    amount             INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    vat_amount         INTEGER NOT NULL DEFAULT 0 CHECK (vat_amount >= 0),
    source_document_id INTEGER,
    source_line_no     INTEGER,
    memo               TEXT NOT NULL DEFAULT '',
    CHECK ((source_document_id IS NULL) = (source_line_no IS NULL)),
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, cost_type_id) REFERENCES landed_cost_types(company_id, id),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, source_document_id) REFERENCES documents(company_id, id),
    UNIQUE (document_id, line_no),
    UNIQUE (company_id, id)
);
CREATE INDEX landed_cost_charges_by_source
    ON landed_cost_charges (company_id, source_document_id, source_line_no);

-- Calculated when posted: each charge's share of each receipt line of the batch.
CREATE TABLE landed_cost_shares (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    charge_id   INTEGER NOT NULL,
    line_id     INTEGER NOT NULL,
    amount      INTEGER NOT NULL CHECK (amount > 0),
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, charge_id)
        REFERENCES landed_cost_charges(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, line_id)
        REFERENCES inventory_lines(company_id, id) ON DELETE CASCADE,
    UNIQUE (charge_id, line_id)
);

-- Existing landed cost documents: one charge (their single credit account), allocated
-- by the amounts already stored on their lines.
INSERT INTO landed_cost_charges
    (company_id, document_id, line_no, cost_type_id, account_id, sc1, sc2, sc3, amount)
SELECT d.company_id, d.id, 1, d.landed_cost_type_id,
       MIN(l.offset_account_id), MIN(l.offset_sc1), MIN(l.offset_sc2), MIN(l.offset_sc3),
       SUM(l.amount)
FROM inventory_documents d
JOIN inventory_lines l ON l.document_id = d.id
WHERE d.doc_type = 'landed_cost'
GROUP BY d.id;

INSERT INTO landed_cost_shares (company_id, document_id, charge_id, line_id, amount)
SELECT l.company_id, l.document_id, c.id, l.id, l.amount
FROM inventory_lines l
JOIN inventory_documents d ON d.id = l.document_id
JOIN landed_cost_charges c ON c.document_id = d.id
WHERE d.doc_type = 'landed_cost' AND d.status = 'posted' AND l.amount > 0;

DROP TRIGGER inventory_documents_posted_no_update;
UPDATE inventory_documents SET allocation_method = 'manual' WHERE doc_type = 'landed_cost';
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
)
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

CREATE TRIGGER landed_cost_charges_posted_no_insert BEFORE INSERT ON landed_cost_charges
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_cost_charges_posted_no_update BEFORE UPDATE ON landed_cost_charges
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_cost_charges_posted_no_delete BEFORE DELETE ON landed_cost_charges
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

CREATE TRIGGER landed_cost_shares_posted_no_insert BEFORE INSERT ON landed_cost_shares
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_cost_shares_posted_no_update BEFORE UPDATE ON landed_cost_shares
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_cost_shares_posted_no_delete BEFORE DELETE ON landed_cost_shares
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
