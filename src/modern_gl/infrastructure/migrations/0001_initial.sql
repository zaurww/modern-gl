-- Initial schema. Money is stored as INTEGER minor units (qəpik / kopeks).
-- Every child table carries company_id and uses composite foreign keys
-- (company_id, id) so a row can never reference another company's data.

CREATE TABLE companies (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    base_currency  TEXT NOT NULL DEFAULT 'AZN',
    closed_through TEXT,  -- ISO date; documents dated on or before it cannot be posted
    created_at     TEXT NOT NULL
);

CREATE TABLE layers (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);

CREATE TABLE subconto_kinds (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);

CREATE TABLE subconto_values (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL,
    kind_id    INTEGER NOT NULL,
    code       TEXT,
    name       TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (company_id, kind_id) REFERENCES subconto_kinds(company_id, id),
    UNIQUE (kind_id, code),
    UNIQUE (company_id, id)
);

CREATE TABLE accounts (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    parent_id   INTEGER,
    kind        TEXT NOT NULL CHECK (kind IN ('A', 'P', 'AP')),
    is_group    INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    sc1_kind_id INTEGER,
    sc2_kind_id INTEGER,
    sc3_kind_id INTEGER,
    FOREIGN KEY (company_id, parent_id)   REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1_kind_id) REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, sc2_kind_id) REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, sc3_kind_id) REFERENCES subconto_kinds(company_id, id),
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);

CREATE TABLE documents (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    number      INTEGER NOT NULL,
    doc_date    TEXT NOT NULL CHECK (doc_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    memo        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL CHECK (status IN ('draft', 'posted')),
    layer_id    INTEGER NOT NULL,
    reversal_of INTEGER,  -- set on a red-storno document; points to the reversed one
    created_at  TEXT NOT NULL,
    posted_at   TEXT,
    FOREIGN KEY (company_id, layer_id)    REFERENCES layers(company_id, id),
    FOREIGN KEY (company_id, reversal_of) REFERENCES documents(company_id, id),
    UNIQUE (company_id, number),
    UNIQUE (company_id, id),
    UNIQUE (reversal_of)
);

-- One posting = one Dt/Ct pair (1C style), so every posting is balanced by construction.
CREATE TABLE postings (
    id                INTEGER PRIMARY KEY,
    company_id        INTEGER NOT NULL,
    document_id       INTEGER NOT NULL,
    line_no           INTEGER NOT NULL,
    debit_account_id  INTEGER NOT NULL,
    credit_account_id INTEGER NOT NULL,
    amount            INTEGER NOT NULL CHECK (amount <> 0),
    dt_sc1 INTEGER, dt_sc2 INTEGER, dt_sc3 INTEGER,
    ct_sc1 INTEGER, ct_sc2 INTEGER, ct_sc3 INTEGER,
    memo              TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (company_id, document_id) REFERENCES documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, debit_account_id)  REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, credit_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, dt_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, dt_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, dt_sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc3) REFERENCES subconto_values(company_id, id),
    UNIQUE (document_id, line_no)
);

CREATE TABLE audit_events (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER,
    at         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  INTEGER,
    action     TEXT NOT NULL,
    details    TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX documents_by_company_date ON documents (company_id, status, doc_date);
CREATE INDEX postings_by_debit  ON postings (company_id, debit_account_id);
CREATE INDEX postings_by_credit ON postings (company_id, credit_account_id);
CREATE INDEX audit_by_entity ON audit_events (entity, entity_id);

-- Defense in depth: the application already enforces these rules.
CREATE TRIGGER documents_posted_no_update BEFORE UPDATE ON documents
WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted document is immutable'); END;

CREATE TRIGGER documents_posted_no_delete BEFORE DELETE ON documents
WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted document cannot be deleted'); END;

CREATE TRIGGER postings_posted_no_insert BEFORE INSERT ON postings
WHEN (SELECT status FROM documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted document is immutable'); END;

CREATE TRIGGER postings_posted_no_update BEFORE UPDATE ON postings
WHEN (SELECT status FROM documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted document is immutable'); END;

CREATE TRIGGER postings_posted_no_delete BEFORE DELETE ON postings
WHEN (SELECT status FROM documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted document is immutable'); END;

CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit trail is append-only'); END;

CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit trail is append-only'); END;
