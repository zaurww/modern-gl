-- A period marked reconciled with the portal remembers the books it agreed with (the
-- e-qaimə of the period: number, total, ƏDV — a digest): a correction posted later to an
-- e-qaimə of the period (D140) shows the mark is no longer true. NULL: marked before.
ALTER TABLE eqaime_reconciled ADD COLUMN book_digest TEXT
    CHECK (book_digest IS NULL OR length(book_digest) = 64);
