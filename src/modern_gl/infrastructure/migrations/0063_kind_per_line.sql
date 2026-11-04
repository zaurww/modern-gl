-- A directory of objects or of categories (D-new, refines D173): a purchase line on
-- account 12 with a user-made directory of low-value items took the element typed on the
-- first line for all nine lines, as a cost item does. Which directories are objects (each
-- line of a purchase its own element, named by the line) was a list in the code (fixed
-- assets, intangibles); now it is a property of the directory the user sets.

ALTER TABLE subconto_kinds ADD COLUMN per_line INTEGER NOT NULL DEFAULT 0
    CHECK (per_line IN (0, 1));

UPDATE subconto_kinds SET per_line = 1 WHERE code IN ('fixed_asset', 'intangible');

-- the integer guards of 0053, with the new column
DROP TRIGGER subconto_kinds_integers_insert;
DROP TRIGGER subconto_kinds_integers_update;

CREATE TRIGGER subconto_kinds_integers_insert BEFORE INSERT ON subconto_kinds
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.owner_kind_id) NOT IN ('integer', 'null')
   OR typeof(NEW.per_line) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'subconto_kinds: not an integer'); END;

CREATE TRIGGER subconto_kinds_integers_update BEFORE UPDATE ON subconto_kinds
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.owner_kind_id IS NOT OLD.owner_kind_id AND typeof(NEW.owner_kind_id) NOT IN ('integer', 'null'))
   OR (NEW.per_line IS NOT OLD.per_line AND typeof(NEW.per_line) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'subconto_kinds: not an integer'); END;
