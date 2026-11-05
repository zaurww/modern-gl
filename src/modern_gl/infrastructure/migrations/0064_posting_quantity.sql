-- Quantity in the books (D199): a posting on an account of objects (01, 08, 12 with
-- its own directory…) may say how many — in millionths of a unit, as the stock module
-- counts (domain.quantity); its sign follows the amount (a storno is negative). NULL:
-- no quantity. Which accounts are counted is not stored: it follows their subconto
-- (application/quantities.py).

ALTER TABLE postings ADD COLUMN quantity INTEGER CHECK (quantity IS NULL OR quantity <> 0);

-- the integer guards of 0053, with the new column
DROP TRIGGER postings_integers_insert;
DROP TRIGGER postings_integers_update;

CREATE TRIGGER postings_integers_insert BEFORE INSERT ON postings
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.debit_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.credit_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_amount) NOT IN ('integer', 'null')
   OR typeof(NEW.pays_vat) NOT IN ('integer', 'null')
   OR typeof(NEW.quantity) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'postings: not an integer'); END;

CREATE TRIGGER postings_integers_update BEFORE UPDATE ON postings
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.line_no IS NOT OLD.line_no AND typeof(NEW.line_no) NOT IN ('integer', 'null'))
   OR (NEW.debit_account_id IS NOT OLD.debit_account_id AND typeof(NEW.debit_account_id) NOT IN ('integer', 'null'))
   OR (NEW.credit_account_id IS NOT OLD.credit_account_id AND typeof(NEW.credit_account_id) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc1 IS NOT OLD.dt_sc1 AND typeof(NEW.dt_sc1) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc2 IS NOT OLD.dt_sc2 AND typeof(NEW.dt_sc2) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc3 IS NOT OLD.dt_sc3 AND typeof(NEW.dt_sc3) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc1 IS NOT OLD.ct_sc1 AND typeof(NEW.ct_sc1) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc2 IS NOT OLD.ct_sc2 AND typeof(NEW.ct_sc2) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc3 IS NOT OLD.ct_sc3 AND typeof(NEW.ct_sc3) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.currency_amount IS NOT OLD.currency_amount AND typeof(NEW.currency_amount) NOT IN ('integer', 'null'))
   OR (NEW.pays_vat IS NOT OLD.pays_vat AND typeof(NEW.pays_vat) NOT IN ('integer', 'null'))
   OR (NEW.quantity IS NOT OLD.quantity AND typeof(NEW.quantity) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'postings: not an integer'); END;
