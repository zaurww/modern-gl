-- The language the program writes its own texts into the company's documents in (D-new):
-- «Bank komissiyası» or «Комиссия банка» in a posting, whatever the interface is. NULL — a
-- file of an older program: its texts tell (application/document_language.py).
ALTER TABLE companies ADD COLUMN document_language TEXT
    CHECK (document_language IS NULL OR document_language IN ('az', 'ru'));
