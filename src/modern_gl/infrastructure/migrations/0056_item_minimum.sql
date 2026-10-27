-- The minimum stock of an item (D154): below it on all warehouses together, «Bu gün» and
-- «Склад» say so and offer a purchase of what is missing. In millionths of the item's
-- unit, as every quantity; NULL — no minimum.

ALTER TABLE inventory_items ADD COLUMN min_quantity INTEGER
    CHECK (min_quantity IS NULL OR min_quantity > 0);

DROP TRIGGER inventory_items_integers_insert;
DROP TRIGGER inventory_items_integers_update;

CREATE TRIGGER inventory_items_integers_insert BEFORE INSERT ON inventory_items
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.subconto_value_id) NOT IN ('integer', 'null')
   OR typeof(NEW.unit_id) NOT IN ('integer', 'null')
   OR typeof(NEW.inventory_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.min_quantity) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_items: not an integer'); END;

CREATE TRIGGER inventory_items_integers_update BEFORE UPDATE ON inventory_items
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.subconto_value_id IS NOT OLD.subconto_value_id AND typeof(NEW.subconto_value_id) NOT IN ('integer', 'null'))
   OR (NEW.unit_id IS NOT OLD.unit_id AND typeof(NEW.unit_id) NOT IN ('integer', 'null'))
   OR (NEW.inventory_account_id IS NOT OLD.inventory_account_id AND typeof(NEW.inventory_account_id) NOT IN ('integer', 'null'))
   OR (NEW.min_quantity IS NOT OLD.min_quantity AND typeof(NEW.min_quantity) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_items: not an integer'); END;
