-- Advance reports (D-new-advance-reports): an employee accounts for the money given to
-- spend for the company (71). A document that builds its own GL postings, like a bank
-- operation: the GL document carries the number, date, memo and status; these rows keep
-- what was entered. Each line: Dt its account (an expense, a supplier paid…) / Kt the
-- accountable account with the employee.

CREATE TABLE advance_reports (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    document_id INTEGER NOT NULL,
    account_id  INTEGER,  -- the accountable account (71); NULL only in a draft
    employee_id INTEGER,  -- the employee (an element of the employee directory)
    FOREIGN KEY (company_id, document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, employee_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id),
    UNIQUE (company_id, document_id)
);
CREATE INDEX advance_reports_account ON advance_reports (company_id, account_id);
CREATE INDEX advance_reports_employee ON advance_reports (company_id, employee_id);

CREATE TABLE advance_report_lines (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    report_id  INTEGER NOT NULL,
    line_no    INTEGER NOT NULL CHECK (line_no > 0),
    account_id INTEGER,  -- what the money went on (NULL only in a draft)
    sc1        INTEGER,
    sc2        INTEGER,
    sc3        INTEGER,
    amount     INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    memo       TEXT NOT NULL DEFAULT '',  -- the receipt: «Çek №0012, yanacaq»
    FOREIGN KEY (company_id, report_id) REFERENCES advance_reports(company_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc3) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, report_id, line_no)
);
CREATE INDEX advance_report_lines_account ON advance_report_lines (company_id, account_id);
CREATE INDEX advance_report_lines_sc1 ON advance_report_lines (company_id, sc1);
CREATE INDEX advance_report_lines_sc2 ON advance_report_lines (company_id, sc2);
CREATE INDEX advance_report_lines_sc3 ON advance_report_lines (company_id, sc3);

-- whole numbers only (as 0053 for every table)
CREATE TRIGGER advance_reports_integers_insert BEFORE INSERT ON advance_reports
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.employee_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'advance_reports: not an integer'); END;

CREATE TRIGGER advance_reports_integers_update BEFORE UPDATE ON advance_reports
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.employee_id IS NOT OLD.employee_id AND typeof(NEW.employee_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'advance_reports: not an integer'); END;

CREATE TRIGGER advance_report_lines_integers_insert BEFORE INSERT ON advance_report_lines
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.report_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'advance_report_lines: not an integer'); END;

CREATE TRIGGER advance_report_lines_integers_update BEFORE UPDATE ON advance_report_lines
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.report_id IS NOT OLD.report_id AND typeof(NEW.report_id) NOT IN ('integer', 'null'))
   OR (NEW.line_no IS NOT OLD.line_no AND typeof(NEW.line_no) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.sc1 IS NOT OLD.sc1 AND typeof(NEW.sc1) NOT IN ('integer', 'null'))
   OR (NEW.sc2 IS NOT OLD.sc2 AND typeof(NEW.sc2) NOT IN ('integer', 'null'))
   OR (NEW.sc3 IS NOT OLD.sc3 AND typeof(NEW.sc3) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'advance_report_lines: not an integer'); END;

-- the module names its GL documents: «Avans hesabatı №…»
DROP VIEW document_owners;

CREATE VIEW document_owners AS
SELECT company_id, gl_document_id AS document_id, 'inventory' AS module, 'made' AS role,
       id AS owner_id, number AS owner_number, doc_type AS owner_kind
FROM inventory_documents WHERE gl_document_id IS NOT NULL
UNION ALL
SELECT a.company_id, a.gl_document_id, 'inventory', 'made', d.id, d.number, d.doc_type
FROM inventory_accruals a
JOIN inventory_documents d ON d.company_id = a.company_id AND d.id = a.document_id
UNION ALL
SELECT company_id, document_id, 'conversion', 'made', id, NULL, 'conversion'
FROM currency_conversions WHERE document_id IS NOT NULL
UNION ALL
SELECT company_id, credit_document_id, 'conversion', 'made', id, NULL, 'conversion'
FROM currency_conversions WHERE credit_document_id IS NOT NULL
UNION ALL
SELECT o.company_id, o.document_id, 'bank', 'made', o.id, NULL,
       CASE WHEN a.account_type = 'cash' THEN 'cash_' ELSE 'bank_' END || o.direction
FROM bank_operations o
LEFT JOIN accounts a ON a.company_id = o.company_id AND a.id = o.account_id
WHERE o.document_id IS NOT NULL
UNION ALL
SELECT company_id, document_id, 'accountable', 'made', id, NULL, 'advance_report'
FROM advance_reports
UNION ALL
SELECT c.company_id, c.source_document_id, 'landed_cost', 'uses', d.id, d.number, 'landed_cost'
FROM landed_cost_charges c
JOIN inventory_documents d ON d.company_id = c.company_id AND d.id = c.document_id
WHERE c.source_document_id IS NOT NULL;
