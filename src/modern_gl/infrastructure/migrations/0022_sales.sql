-- «Продажа / Satış»: a warehouse document of its own type. Its lines are goods (taken from
-- stock at the average cost, like an issue) or services: a line without an item. A sale
-- line keeps the revenue without VAT in `amount`, its VAT in `vat_amount`, the cost of the
-- goods in `expense_amount` and the account the cost went to in `cost_account_id` (late
-- landed cost follows it there). `offset_*` is the customer's settlement account.
-- SQLite cannot change a CHECK or NOT NULL in place: both tables are rebuilt, ids kept.
-- In legacy mode the rename leaves the other tables' references and triggers as they are:
-- they name the tables, which the rebuilt ones take over.

PRAGMA legacy_alter_table = ON;

CREATE TABLE inventory_documents_new (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    number         INTEGER NOT NULL,
    doc_date       TEXT NOT NULL
        CHECK (doc_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    doc_type       TEXT NOT NULL CHECK (
        doc_type IN ('opening', 'receipt', 'issue', 'transfer', 'landed_cost', 'sale')
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
    FOREIGN KEY (company_id, gl_document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, landed_cost_type_id)
        REFERENCES landed_cost_types(company_id, id),
    UNIQUE (company_id, number),
    UNIQUE (company_id, id),
    UNIQUE (gl_document_id)
);

INSERT INTO inventory_documents_new (id, company_id, number, doc_date, doc_type, memo, status,
    landed_cost_type_id, gl_document_id, created_at, posted_at, vat_rate, allocation_method,
    currency_id, currency_rate, invoice, invoice_kind)
SELECT id, company_id, number, doc_date, doc_type, memo, status,
    landed_cost_type_id, gl_document_id, created_at, posted_at, vat_rate, allocation_method,
    currency_id, currency_rate, invoice, invoice_kind
FROM inventory_documents;

DROP TABLE inventory_documents;
ALTER TABLE inventory_documents_new RENAME TO inventory_documents;

CREATE INDEX inventory_documents_by_company_date
    ON inventory_documents (company_id, status, doc_date, id);

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

CREATE TRIGGER inventory_documents_posted_no_delete BEFORE DELETE ON inventory_documents
WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document cannot be deleted'); END;

CREATE TABLE inventory_lines_new (
    id                   INTEGER PRIMARY KEY,
    company_id           INTEGER NOT NULL,
    document_id          INTEGER NOT NULL,
    line_no              INTEGER NOT NULL,
    item_id              INTEGER,  -- NULL: a service line of a sale
    warehouse_id         INTEGER,
    to_warehouse_id      INTEGER,
    quantity             INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    amount               INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    inventory_amount     INTEGER NOT NULL DEFAULT 0 CHECK (inventory_amount >= 0),
    expense_amount       INTEGER NOT NULL DEFAULT 0 CHECK (expense_amount >= 0),
    offset_account_id    INTEGER,
    offset_sc1           INTEGER,
    offset_sc2           INTEGER,
    offset_sc3           INTEGER,
    source_receipt_line_id INTEGER,
    memo                 TEXT NOT NULL DEFAULT '',
    vat_amount           INTEGER NOT NULL DEFAULT 0 CHECK (vat_amount >= 0),
    currency_amount      INTEGER CHECK (currency_amount IS NULL OR currency_amount >= 0),
    cost_account_id      INTEGER,
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, item_id) REFERENCES inventory_items(company_id, id),
    FOREIGN KEY (company_id, warehouse_id) REFERENCES warehouses(company_id, id),
    FOREIGN KEY (company_id, to_warehouse_id) REFERENCES warehouses(company_id, id),
    FOREIGN KEY (company_id, offset_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, offset_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, offset_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, offset_sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, source_receipt_line_id)
        REFERENCES inventory_lines(company_id, id),
    FOREIGN KEY (company_id, cost_account_id) REFERENCES accounts(company_id, id),
    UNIQUE (document_id, line_no),
    UNIQUE (company_id, id)
);

INSERT INTO inventory_lines_new (id, company_id, document_id, line_no, item_id, warehouse_id,
    to_warehouse_id, quantity, amount, inventory_amount, expense_amount, offset_account_id,
    offset_sc1, offset_sc2, offset_sc3, source_receipt_line_id, memo, vat_amount,
    currency_amount)
SELECT id, company_id, document_id, line_no, item_id, warehouse_id,
    to_warehouse_id, quantity, amount, inventory_amount, expense_amount, offset_account_id,
    offset_sc1, offset_sc2, offset_sc3, source_receipt_line_id, memo, vat_amount,
    currency_amount
FROM inventory_lines;

DROP TABLE inventory_lines;
ALTER TABLE inventory_lines_new RENAME TO inventory_lines;

CREATE TRIGGER inventory_lines_posted_no_insert BEFORE INSERT ON inventory_lines
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER inventory_lines_posted_no_update BEFORE UPDATE ON inventory_lines
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER inventory_lines_posted_no_delete BEFORE DELETE ON inventory_lines
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

PRAGMA legacy_alter_table = OFF;

-- Accounts a sale posts to (roles, D34): the revenue, the cost of the goods, the VAT to
-- pay, and the account the VAT is charged from (`sales_vat`; none: from the customer's
-- account). The 1C 7.7 chart: 90.1 / 90.2 / 68.2 / 90.3; «classic»: 46 / 46 / 68.2 / 46
-- (Дт 62 / Кт 46 with VAT, Дт 46 / Кт 68.2 — as its «Реализация с НДС» template does).
INSERT OR IGNORE INTO account_roles (company_id, role, account_id)
SELECT company_id, 'sales_revenue', id FROM accounts
WHERE is_group = 0 AND active = 1 AND account_type = 'sales'
  AND (code = '90.1' OR (code = '46' AND NOT EXISTS (
      SELECT 1 FROM accounts b WHERE b.company_id = accounts.company_id AND b.code = '90.1'
  )));

INSERT OR IGNORE INTO account_roles (company_id, role, account_id)
SELECT company_id, 'cost_of_sales', id FROM accounts
WHERE is_group = 0 AND active = 1
  AND ((code = '90.2' AND account_type = 'cost_of_sales')
    OR (code = '46' AND account_type = 'sales' AND NOT EXISTS (
      SELECT 1 FROM accounts b WHERE b.company_id = accounts.company_id AND b.code = '90.2'
  )));

INSERT OR IGNORE INTO account_roles (company_id, role, account_id)
SELECT company_id, 'sales_vat', id FROM accounts
WHERE is_group = 0 AND active = 1 AND account_type = 'sales'
  AND (code = '90.3' OR (code = '46' AND NOT EXISTS (
      SELECT 1 FROM accounts b WHERE b.company_id = accounts.company_id AND b.code = '90.3'
  )));

INSERT OR IGNORE INTO account_roles (company_id, role, account_id)
SELECT company_id, 'output_vat', id FROM accounts
WHERE is_group = 0 AND active = 1 AND code = '68.2' AND account_type = 'tax_payable';
