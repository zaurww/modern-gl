-- A purchase (receipt) line without an item: a service, a fixed asset or any expense
-- (D43). Its value goes to `cost_account_id` (26, 44, 08…) with these subconto (cost item,
-- fixed asset…); no stock moves. Columns added by ALTER cannot carry the composite FK:
-- the application and the GL posting check the values belong to the company.

ALTER TABLE inventory_lines ADD COLUMN cost_sc1 INTEGER;
ALTER TABLE inventory_lines ADD COLUMN cost_sc2 INTEGER;
ALTER TABLE inventory_lines ADD COLUMN cost_sc3 INTEGER;
