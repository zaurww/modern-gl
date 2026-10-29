-- The import's note on a bank operation (D186): why the line was left a
-- draft («новый контрагент — проверьте»), why it went to the unidentified account, or
-- what it replaced. Shown in the statement next to the line, so the reason outlives the
-- import window. Cleared when a person saves the operation: they have seen it.

ALTER TABLE bank_operations ADD COLUMN note TEXT NOT NULL DEFAULT '';
