-- The receipts an issue or a sale takes its goods from are found by the item (debt 6):
-- without this index every one of them read all the warehouse rows of the company, and a
-- year's recalculation (about 1 000 documents of the demo year) took 2.9 s.
CREATE INDEX inventory_lines_by_item ON inventory_lines (company_id, item_id);
