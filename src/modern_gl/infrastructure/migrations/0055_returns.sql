-- Returns (D153): goods back to the supplier, goods back from a customer — each a document
-- type of its own, posted the other way round from its purchase or sale (Dt 60 / Ct 41 and
-- the input ƏDV; Dt 46 / Ct 62, the ƏDV and the cost back to stock), with the number of the
-- return e-qaimə («malların geri qaytarılması»). A return line may name the line of the
-- purchase or sale it returns (`inventory_returns`): its price, its cost, how much is left
-- to return.
-- SQLite cannot change a CHECK in place: the table is rebuilt with its ids, indexes and
-- triggers, as in 0037; in legacy mode the other tables' references keep naming it.

PRAGMA legacy_alter_table = ON;

CREATE TABLE inventory_documents_new (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    number              INTEGER NOT NULL,
    doc_date            TEXT NOT NULL
        CHECK (doc_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    doc_type            TEXT NOT NULL CHECK (
        doc_type IN (
            'opening', 'receipt', 'incoming', 'issue', 'transfer', 'landed_cost', 'sale',
            'purchase_return', 'sale_return'
        )
    ),
    memo                TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL CHECK (status IN ('draft', 'posted')),
    landed_cost_type_id INTEGER,
    gl_document_id      INTEGER,
    created_at          TEXT NOT NULL,
    posted_at           TEXT,
    vat_rate            INTEGER CHECK (vat_rate IS NULL OR vat_rate BETWEEN 0 AND 10000),
    allocation_method   TEXT
        CHECK (allocation_method IS NULL OR allocation_method IN ('value', 'quantity', 'manual')),
    currency_id         INTEGER,
    currency_rate       INTEGER CHECK (currency_rate IS NULL OR currency_rate > 0),
    invoice             TEXT
        CHECK (invoice IS NULL OR (TRIM(invoice) <> '' AND invoice = upper(invoice))),
    invoice_kind        TEXT
        CHECK (invoice_kind IS NULL OR (invoice_kind = 'customs' AND invoice IS NOT NULL)),
    incoming_reason     TEXT CHECK (
        incoming_reason IS NULL
        OR incoming_reason IN ('surplus', 'contribution', 'production', 'gift')
    ),
    awaits_invoice      INTEGER NOT NULL DEFAULT 0
        CHECK (awaits_invoice IN (0, 1)
               AND (awaits_invoice = 0 OR (doc_type = 'receipt' AND invoice IS NULL))),
    CHECK ((doc_type = 'incoming') = (incoming_reason IS NOT NULL)),
    FOREIGN KEY (company_id, gl_document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, landed_cost_type_id)
        REFERENCES landed_cost_types(company_id, id),
    FOREIGN KEY (company_id, currency_id) REFERENCES currencies(company_id, id),
    UNIQUE (company_id, number),
    UNIQUE (company_id, id),
    UNIQUE (gl_document_id)
);

INSERT INTO inventory_documents_new (
    id, company_id, number, doc_date, doc_type, memo, status, landed_cost_type_id, gl_document_id,
    created_at, posted_at, vat_rate, allocation_method, currency_id, currency_rate, invoice,
    invoice_kind, incoming_reason, awaits_invoice)
SELECT id, company_id, number, doc_date, doc_type, memo, status, landed_cost_type_id, gl_document_id,
    created_at, posted_at, vat_rate, allocation_method, currency_id, currency_rate, invoice,
    invoice_kind, incoming_reason, awaits_invoice
FROM inventory_documents;

DROP TABLE inventory_documents;
ALTER TABLE inventory_documents_new RENAME TO inventory_documents;

CREATE INDEX inventory_documents_awaiting
    ON inventory_documents (company_id, awaits_invoice, doc_date);

CREATE INDEX inventory_documents_by_company_date
    ON inventory_documents (company_id, status, doc_date, id);

CREATE TRIGGER inventory_documents_closed_no_insert BEFORE INSERT ON inventory_documents
WHEN NEW.status = 'posted' AND NEW.doc_date <= (SELECT closed_through FROM companies WHERE id = NEW.company_id)
BEGIN SELECT RAISE(ABORT, 'period is closed: inventory document not posted'); END;

CREATE TRIGGER inventory_documents_closed_no_update BEFORE UPDATE ON inventory_documents
WHEN (OLD.status = 'posted' AND OLD.doc_date <= (SELECT closed_through FROM companies WHERE id = OLD.company_id))
  OR (NEW.status = 'posted' AND OLD.status <> 'posted'
      AND NEW.doc_date <= (SELECT closed_through FROM companies WHERE id = NEW.company_id))
BEGIN SELECT RAISE(ABORT, 'period is closed: posted inventory document is unchanged'); END;

CREATE TRIGGER inventory_documents_integers_insert BEFORE INSERT ON inventory_documents
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.number) NOT IN ('integer', 'null')
   OR typeof(NEW.landed_cost_type_id) NOT IN ('integer', 'null')
   OR typeof(NEW.gl_document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.vat_rate) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_rate) NOT IN ('integer', 'null')
   OR typeof(NEW.awaits_invoice) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_documents: not an integer'); END;

CREATE TRIGGER inventory_documents_integers_update BEFORE UPDATE ON inventory_documents
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.number IS NOT OLD.number AND typeof(NEW.number) NOT IN ('integer', 'null'))
   OR (NEW.landed_cost_type_id IS NOT OLD.landed_cost_type_id AND typeof(NEW.landed_cost_type_id) NOT IN ('integer', 'null'))
   OR (NEW.gl_document_id IS NOT OLD.gl_document_id AND typeof(NEW.gl_document_id) NOT IN ('integer', 'null'))
   OR (NEW.vat_rate IS NOT OLD.vat_rate AND typeof(NEW.vat_rate) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.currency_rate IS NOT OLD.currency_rate AND typeof(NEW.currency_rate) NOT IN ('integer', 'null'))
   OR (NEW.awaits_invoice IS NOT OLD.awaits_invoice AND typeof(NEW.awaits_invoice) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_documents: not an integer'); END;

CREATE TRIGGER inventory_documents_posted_no_delete BEFORE DELETE ON inventory_documents
WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document cannot be deleted'); END;

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

PRAGMA legacy_alter_table = OFF;


CREATE TABLE inventory_returns (
    id               INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL,
    document_id      INTEGER NOT NULL,  -- the return
    line_id          INTEGER NOT NULL,  -- its line
    returned_line_id INTEGER NOT NULL,  -- the purchase's or sale's line it returns
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, line_id) REFERENCES inventory_lines(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, returned_line_id) REFERENCES inventory_lines(company_id, id),
    UNIQUE (line_id),
    UNIQUE (company_id, id)
);
CREATE INDEX inventory_returns_by_document ON inventory_returns (company_id, document_id);
CREATE INDEX inventory_returns_by_returned ON inventory_returns (company_id, returned_line_id);

CREATE TRIGGER inventory_returns_integers_insert BEFORE INSERT ON inventory_returns
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.returned_line_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_returns: not an integer'); END;

CREATE TRIGGER inventory_returns_integers_update BEFORE UPDATE ON inventory_returns
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.line_id IS NOT OLD.line_id AND typeof(NEW.line_id) NOT IN ('integer', 'null'))
   OR (NEW.returned_line_id IS NOT OLD.returned_line_id
       AND typeof(NEW.returned_line_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_returns: not an integer'); END;

CREATE TRIGGER inventory_returns_posted_no_insert BEFORE INSERT ON inventory_returns
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

CREATE TRIGGER inventory_returns_posted_no_update BEFORE UPDATE ON inventory_returns
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

CREATE TRIGGER inventory_returns_posted_no_delete BEFORE DELETE ON inventory_returns
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
