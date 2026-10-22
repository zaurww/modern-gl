-- How the company is kept (D90): 'full' — the whole program; 'stock' — only the warehouse,
-- purchases and sales with their directories, for a client who keeps the books elsewhere.
-- The postings are made either way: in 'stock' the books are only not shown.

ALTER TABLE companies ADD COLUMN mode TEXT NOT NULL DEFAULT 'full'
    CHECK (mode IN ('full', 'stock'));
