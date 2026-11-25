-- An expense of a batch names the purchase of the goods it is for: the broker's or the
-- terminal's service line (it waits on the account of procurement) -> the purchase with the
-- declaration. A note for the one who gathers the batch, not a source of postings: the
-- expense still waits until a «Расходы по партии» document takes it. A line has one purchase;
-- an e-qaimə for several declarations is split into lines. The link goes with its line and
-- its document; the purchase of the goods cannot go while a link names it (the program takes
-- the links away first).
CREATE TABLE inventory_expense_targets (
    id                 INTEGER PRIMARY KEY,
    company_id         INTEGER NOT NULL,
    document_id        INTEGER NOT NULL,  -- the purchase with the expense
    line_id            INTEGER NOT NULL,  -- its service line
    target_document_id INTEGER NOT NULL,  -- the purchase of the goods
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, line_id) REFERENCES inventory_lines(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, target_document_id) REFERENCES inventory_documents(company_id, id),
    UNIQUE (line_id),
    UNIQUE (company_id, id),
    CHECK (target_document_id <> document_id)
);
CREATE INDEX inventory_expense_targets_by_document
    ON inventory_expense_targets (company_id, document_id);
CREATE INDEX inventory_expense_targets_by_line ON inventory_expense_targets (company_id, line_id);
CREATE INDEX inventory_expense_targets_by_target
    ON inventory_expense_targets (company_id, target_document_id);

CREATE TRIGGER inventory_expense_targets_integers_insert BEFORE INSERT ON inventory_expense_targets
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.target_document_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_expense_targets: not an integer'); END;

CREATE TRIGGER inventory_expense_targets_integers_update BEFORE UPDATE ON inventory_expense_targets
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.target_document_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_expense_targets: not an integer'); END;
