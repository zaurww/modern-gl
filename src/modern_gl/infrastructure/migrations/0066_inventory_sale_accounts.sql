-- The accounts a sale of goods posts to, by the stock account of the goods: the revenue
-- and the cost of sales of «Товары» (41) may differ from those of «Материалы» (10) or
-- «Готовая продукция» (43). The warehouse's own table: the core's account_roles keeps
-- the one account of the whole company, taken when a stock account has none of its own.
-- A row says nothing about what is posted already: the warehouse posts its sales again
-- when a row changes (what is in the closed period stays).

CREATE TABLE inventory_sale_accounts (
    id               INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies(id),
    stock_account_id INTEGER NOT NULL,  -- the stock account of the goods sold
    role             TEXT NOT NULL CHECK (role IN ('sales_revenue', 'cost_of_sales')),
    account_id       INTEGER NOT NULL,  -- the account their sale posts to
    FOREIGN KEY (company_id, stock_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    UNIQUE (company_id, stock_account_id, role),
    UNIQUE (company_id, id)
);
CREATE INDEX inventory_sale_accounts_by_account ON inventory_sale_accounts (company_id, account_id);

CREATE TRIGGER inventory_sale_accounts_integers_insert BEFORE INSERT ON inventory_sale_accounts
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.stock_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_sale_accounts: not an integer'); END;

CREATE TRIGGER inventory_sale_accounts_integers_update BEFORE UPDATE ON inventory_sale_accounts
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.stock_account_id IS NOT OLD.stock_account_id
       AND typeof(NEW.stock_account_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_sale_accounts: not an integer'); END;
