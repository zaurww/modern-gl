-- Groups (folders) in a directory, as in 1C: «Kabellər» holds its items, «Xaricilər» its
-- counterparties. A group is an element with is_group = 1; it has no postings, only
-- elements (and other groups) under it (D60). The group is of the same company and
-- directory — checked by the program (a column added to a table takes no composite key).
-- The branch feat/sale-subconto also has a 0027: the one merged second takes 0028.

ALTER TABLE subconto_values ADD COLUMN parent_id INTEGER REFERENCES subconto_values(id);
ALTER TABLE subconto_values ADD COLUMN is_group INTEGER NOT NULL DEFAULT 0
    CHECK (is_group IN (0, 1));
CREATE INDEX subconto_values_parent ON subconto_values(parent_id);
