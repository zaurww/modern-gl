-- Parallel books (IFRS, tax) are turned on per company (D63). Until then a document has
-- no «Book» field and reports no book switch. A company that already has documents in
-- an adjustment layer keeps them on.

ALTER TABLE companies ADD COLUMN parallel_books INTEGER NOT NULL DEFAULT 0
    CHECK (parallel_books IN (0, 1));

UPDATE companies SET parallel_books = 1
WHERE EXISTS (
    SELECT 1 FROM documents d JOIN layers l ON l.id = d.layer_id
    WHERE d.company_id = companies.id AND l.code <> 'common'
);
