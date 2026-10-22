-- «Mədaxil» (D91): goods come in without a purchase — a surplus found at a stock count, an
-- owner's contribution, own production, a gift. A document type of its own: Dt the stock
-- account / Kt the account of its reason, no supplier, no VAT. `incoming_reason` is that
-- reason, and only a mədaxil has one.
-- SQLite cannot change a CHECK in place: the table is rebuilt, ids kept. In legacy mode the
-- rename leaves the other tables' references, triggers and views as they are: they name the
-- table, which the rebuilt one takes over.

PRAGMA legacy_alter_table = ON;

CREATE TABLE inventory_documents_new (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    number         INTEGER NOT NULL,
    doc_date       TEXT NOT NULL
        CHECK (doc_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    doc_type       TEXT NOT NULL CHECK (
        doc_type IN (
            'opening', 'receipt', 'incoming', 'issue', 'transfer', 'landed_cost', 'sale'
        )
    ),
    memo           TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL CHECK (status IN ('draft', 'posted')),
    landed_cost_type_id INTEGER,
    gl_document_id INTEGER,
    created_at     TEXT NOT NULL,
    posted_at      TEXT,
    vat_rate       INTEGER CHECK (vat_rate IS NULL OR vat_rate BETWEEN 0 AND 10000),
    allocation_method TEXT
        CHECK (allocation_method IS NULL OR allocation_method IN ('value', 'quantity', 'manual')),
    currency_id    INTEGER,
    currency_rate  INTEGER CHECK (currency_rate IS NULL OR currency_rate > 0),
    invoice        TEXT
        CHECK (invoice IS NULL OR (TRIM(invoice) <> '' AND invoice = upper(invoice))),
    invoice_kind   TEXT
        CHECK (invoice_kind IS NULL OR (invoice_kind = 'customs' AND invoice IS NOT NULL)),
    expense_date   TEXT
        CHECK (expense_date IS NULL OR expense_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    accrual_document_id INTEGER REFERENCES documents(id),
    incoming_reason TEXT CHECK (
        incoming_reason IS NULL
        OR incoming_reason IN ('surplus', 'contribution', 'production', 'gift')
    ),
    CHECK ((doc_type = 'incoming') = (incoming_reason IS NOT NULL)),
    FOREIGN KEY (company_id, gl_document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, landed_cost_type_id)
        REFERENCES landed_cost_types(company_id, id),
    UNIQUE (company_id, number),
    UNIQUE (company_id, id),
    UNIQUE (gl_document_id)
);

INSERT INTO inventory_documents_new (id, company_id, number, doc_date, doc_type, memo, status,
    landed_cost_type_id, gl_document_id, created_at, posted_at, vat_rate, allocation_method,
    currency_id, currency_rate, invoice, invoice_kind, expense_date, accrual_document_id)
SELECT id, company_id, number, doc_date, doc_type, memo, status,
    landed_cost_type_id, gl_document_id, created_at, posted_at, vat_rate, allocation_method,
    currency_id, currency_rate, invoice, invoice_kind, expense_date, accrual_document_id
FROM inventory_documents;

DROP TABLE inventory_documents;
ALTER TABLE inventory_documents_new RENAME TO inventory_documents;

CREATE INDEX inventory_documents_by_company_date
    ON inventory_documents (company_id, status, doc_date, id);
CREATE UNIQUE INDEX inventory_documents_by_accrual
    ON inventory_documents (accrual_document_id) WHERE accrual_document_id IS NOT NULL;

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
)
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

CREATE TRIGGER inventory_documents_posted_no_delete BEFORE DELETE ON inventory_documents
WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document cannot be deleted'); END;

PRAGMA legacy_alter_table = OFF;
