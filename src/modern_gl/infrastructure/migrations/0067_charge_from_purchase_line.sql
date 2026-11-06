-- A batch's expense taken from a purchase's service line: the broker's e-qaimə that waits on
-- an account of procurement (15). The line, not its GL posting: a purchase may be posted
-- again and its postings numbered anew, the line stays. The line cannot go while a charge
-- has it; a charge going takes its link with it.
CREATE TABLE landed_cost_charge_lines (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL,
    charge_id      INTEGER NOT NULL,
    source_line_id INTEGER NOT NULL,
    FOREIGN KEY (company_id, charge_id)
        REFERENCES landed_cost_charges(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, source_line_id) REFERENCES inventory_lines(company_id, id),
    UNIQUE (charge_id)
);
CREATE INDEX landed_cost_charge_lines_charge ON landed_cost_charge_lines (company_id, charge_id);
CREATE INDEX landed_cost_charge_lines_source
    ON landed_cost_charge_lines (company_id, source_line_id);

CREATE TRIGGER landed_cost_charge_lines_posted_no_insert BEFORE INSERT ON landed_cost_charge_lines
WHEN (SELECT d.status FROM landed_cost_charges c
      JOIN inventory_documents d ON d.id = c.document_id WHERE c.id = NEW.charge_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_cost_charge_lines_posted_no_update BEFORE UPDATE ON landed_cost_charge_lines
BEGIN SELECT RAISE(ABORT, 'a link of a charge is replaced, not changed'); END;

CREATE TRIGGER landed_cost_charge_lines_integers_insert BEFORE INSERT ON landed_cost_charge_lines
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.charge_id) NOT IN ('integer', 'null')
   OR typeof(NEW.source_line_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'landed_cost_charge_lines: not an integer'); END;
CREATE TRIGGER landed_cost_charge_lines_integers_update BEFORE UPDATE ON landed_cost_charge_lines
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.charge_id) NOT IN ('integer', 'null')
   OR typeof(NEW.source_line_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'landed_cost_charge_lines: not an integer'); END;
