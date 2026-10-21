-- What the tax portal showed of each e-qaimə (D53): written whenever the program reads the
-- portal's list (import, reconciliation), imported or not, so the reconciliation knows
-- what was there and what has changed since. Amounts as the list gives them, minor units.

CREATE TABLE eqaime_portal (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    outgoing      INTEGER NOT NULL CHECK (outgoing IN (0, 1)),  -- 1 sent (a sale)
    number        TEXT NOT NULL CHECK (TRIM(number) <> ''),  -- normalized: domain/invoice.py
    portal_id     TEXT NOT NULL DEFAULT '',  -- for invoice/{id}
    source_system TEXT NOT NULL DEFAULT '',
    doc_date      TEXT NOT NULL,  -- of the e-qaimə on the portal (createdAt)
    party_tin     TEXT NOT NULL DEFAULT '',
    party_name    TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,  -- as the API names it
    kind          TEXT NOT NULL DEFAULT '',
    type          TEXT NOT NULL DEFAULT '',
    total         INTEGER NOT NULL,  -- with ƏDV
    vat           INTEGER NOT NULL,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    UNIQUE (company_id, outgoing, number),
    UNIQUE (company_id, id)
);

-- every change seen on the portal: was -> became (a supplier cancels or corrects later)
CREATE TABLE eqaime_portal_changes (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    portal_id  INTEGER NOT NULL,  -- eqaime_portal.id
    seen_at    TEXT NOT NULL,
    old_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    old_date   TEXT NOT NULL,
    new_date   TEXT NOT NULL,
    old_tin    TEXT NOT NULL,
    new_tin    TEXT NOT NULL,
    old_total  INTEGER NOT NULL,
    new_total  INTEGER NOT NULL,
    old_vat    INTEGER NOT NULL,
    new_vat    INTEGER NOT NULL,
    FOREIGN KEY (company_id, portal_id) REFERENCES eqaime_portal(company_id, id)
);

CREATE INDEX eqaime_portal_changes_entry ON eqaime_portal_changes (company_id, portal_id);

-- a month the user has reconciled with the portal, purchases or sales apart
CREATE TABLE eqaime_reconciled (
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    outgoing      INTEGER NOT NULL CHECK (outgoing IN (0, 1)),
    month         TEXT NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    reconciled_at TEXT NOT NULL,
    PRIMARY KEY (company_id, outgoing, month)
);
