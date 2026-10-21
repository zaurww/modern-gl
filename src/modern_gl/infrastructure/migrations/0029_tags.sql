-- Tags of directory elements (D63): «Связанная сторона», «Арендодатель», «Холдинг X».
-- An element has any number of them, unlike a group (one per element), and reports by
-- subconto filter by a tag. Tags are of the company, not of a directory: a director in
-- «Сотрудники» is a related party too. A tag says nothing to postings, so deleting a tag
-- or an element takes its links with it (ON DELETE CASCADE).

CREATE TABLE tags (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    name       TEXT NOT NULL CHECK (trim(name) <> ''),
    UNIQUE (company_id, name COLLATE NOCASE),
    UNIQUE (company_id, id)
);

CREATE TABLE subconto_value_tags (
    company_id INTEGER NOT NULL REFERENCES companies(id),
    value_id   INTEGER NOT NULL,
    tag_id     INTEGER NOT NULL,
    PRIMARY KEY (value_id, tag_id),
    FOREIGN KEY (company_id, value_id) REFERENCES subconto_values(company_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (company_id, tag_id) REFERENCES tags(company_id, id) ON DELETE CASCADE
);

CREATE INDEX subconto_value_tags_tag ON subconto_value_tags (company_id, tag_id);
