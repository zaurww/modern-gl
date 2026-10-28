-- A bank operation checked by a person (D180): the import posts the lines it
-- is sure of, and a user who checks every line must see which ones they have seen. Set when
-- the user posts the operation in its form or marks it in the statement; the import and a
-- rebuild never set it. Typed by hand and posted already — checked: a person made it.

ALTER TABLE bank_operations ADD COLUMN is_checked INTEGER NOT NULL DEFAULT 0
    CHECK (is_checked IN (0, 1));

UPDATE bank_operations SET is_checked = 1
WHERE reference = ''
  AND document_id IN (SELECT id FROM documents WHERE status = 'posted');

DROP TRIGGER bank_operations_integers_insert;
DROP TRIGGER bank_operations_integers_update;

CREATE TRIGGER bank_operations_integers_insert BEFORE INSERT ON bank_operations
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.counterparty_id) NOT IN ('integer', 'null')
   OR typeof(NEW.is_checked) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'bank_operations: not an integer'); END;

CREATE TRIGGER bank_operations_integers_update BEFORE UPDATE ON bank_operations
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.sc1 IS NOT OLD.sc1 AND typeof(NEW.sc1) NOT IN ('integer', 'null'))
   OR (NEW.sc2 IS NOT OLD.sc2 AND typeof(NEW.sc2) NOT IN ('integer', 'null'))
   OR (NEW.sc3 IS NOT OLD.sc3 AND typeof(NEW.sc3) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.counterparty_id IS NOT OLD.counterparty_id AND typeof(NEW.counterparty_id) NOT IN ('integer', 'null'))
   OR (NEW.is_checked IS NOT OLD.is_checked AND typeof(NEW.is_checked) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'bank_operations: not an integer'); END;
