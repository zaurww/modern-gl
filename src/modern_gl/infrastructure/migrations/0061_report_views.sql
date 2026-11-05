-- Saved views of a report (D190): what the user opened in the trial
-- balance — the splits under the accounts, the order, one column, the precision — kept
-- under a name. In the company's file, not in the program's settings: a view names the
-- accounts and the directory elements of this company. A view says nothing to the
-- postings: deleting it leaves the books as they are.

CREATE TABLE report_views (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    report     TEXT NOT NULL CHECK (trim(report) <> ''),
    name       TEXT NOT NULL CHECK (trim(name) <> ''),
    settings   TEXT NOT NULL,
    UNIQUE (company_id, report, name COLLATE NOCASE),
    UNIQUE (company_id, id)
);

CREATE TRIGGER report_views_integers_insert BEFORE INSERT ON report_views
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'report_views: not an integer'); END;

CREATE TRIGGER report_views_integers_update BEFORE UPDATE ON report_views
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'report_views: not an integer'); END;
