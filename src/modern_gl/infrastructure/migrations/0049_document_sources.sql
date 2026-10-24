-- Where an imported journal document came from (D130, docs/EXCHANGE.md): another program
-- names it by (source, external_id), and a second import of the same file finds it here
-- instead of making it again (docs/ENGINEERING.md 2.4). Deleting the document deletes the
-- mark: an import after that makes it anew.
CREATE TABLE document_sources (
    company_id  INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    source      TEXT NOT NULL CHECK (source <> ''),       -- the program: "etax-ext"
    external_id TEXT NOT NULL CHECK (external_id <> ''),  -- its id of the document
    PRIMARY KEY (company_id, document_id),
    UNIQUE (company_id, source, external_id),
    FOREIGN KEY (company_id) REFERENCES companies (id),
    FOREIGN KEY (company_id, document_id) REFERENCES documents (company_id, id)
        ON DELETE CASCADE
);
