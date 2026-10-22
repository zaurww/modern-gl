-- A row of a document is found by its document (docs/ENGINEERING.md, debt 5): reposting,
-- cancelling or deleting a warehouse document reads and removes its rows this way, and
-- without an index each of them was a full scan of the table.
CREATE INDEX stock_movements_line ON stock_movements (company_id, line_id);
CREATE INDEX stock_consumptions_document ON stock_consumptions (company_id, document_id);
CREATE INDEX landed_cost_expense_allocations_document
    ON landed_cost_expense_allocations (company_id, document_id);
CREATE INDEX landed_cost_shares_document ON landed_cost_shares (company_id, document_id);
CREATE INDEX landed_cost_shares_line ON landed_cost_shares (company_id, line_id);
