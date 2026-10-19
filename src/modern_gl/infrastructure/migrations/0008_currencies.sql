-- Multi-currency accounting (1C 7.7 style).
-- An account with currency = 1 keeps, besides manat, the currency and the amount in it
-- on every posting side that hits it. A posting carries one currency for both sides.
-- Rates are millionths of a manat for `nominal` units (1 USD = 1700000, 100 JPY = ...).

CREATE TABLE currencies (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    code       TEXT NOT NULL CHECK (length(code) = 3 AND code = upper(code)),
    name       TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);

CREATE TABLE currency_rates (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL,
    currency_id INTEGER NOT NULL,
    rate_date   TEXT NOT NULL CHECK (rate_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    rate        INTEGER NOT NULL CHECK (rate > 0),
    nominal     INTEGER NOT NULL DEFAULT 1 CHECK (nominal > 0),
    source      TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'cbar')),
    FOREIGN KEY (company_id, currency_id) REFERENCES currencies(company_id, id),
    UNIQUE (currency_id, rate_date)
);

ALTER TABLE accounts ADD COLUMN currency INTEGER NOT NULL DEFAULT 0;

-- Default currency of a directory element: a bank account in USD, a contract in EUR.
ALTER TABLE subconto_values ADD COLUMN currency_id INTEGER REFERENCES currencies(id);

ALTER TABLE postings ADD COLUMN currency_id INTEGER REFERENCES currencies(id);
ALTER TABLE postings ADD COLUMN currency_amount INTEGER
    CHECK ((currency_id IS NULL) = (currency_amount IS NULL));

-- Added columns cannot carry composite foreign keys: keep companies apart by triggers.
CREATE TRIGGER postings_currency_company_insert BEFORE INSERT ON postings
WHEN NEW.currency_id IS NOT NULL
 AND (SELECT company_id FROM currencies WHERE id = NEW.currency_id) IS NOT NEW.company_id
BEGIN SELECT RAISE(ABORT, 'currency belongs to another company'); END;

CREATE TRIGGER postings_currency_company_update BEFORE UPDATE OF currency_id ON postings
WHEN NEW.currency_id IS NOT NULL
 AND (SELECT company_id FROM currencies WHERE id = NEW.currency_id) IS NOT NEW.company_id
BEGIN SELECT RAISE(ABORT, 'currency belongs to another company'); END;

CREATE TRIGGER subconto_currency_company_insert BEFORE INSERT ON subconto_values
WHEN NEW.currency_id IS NOT NULL
 AND (SELECT company_id FROM currencies WHERE id = NEW.currency_id) IS NOT NEW.company_id
BEGIN SELECT RAISE(ABORT, 'currency belongs to another company'); END;

CREATE TRIGGER subconto_currency_company_update BEFORE UPDATE OF currency_id ON subconto_values
WHEN NEW.currency_id IS NOT NULL
 AND (SELECT company_id FROM currencies WHERE id = NEW.currency_id) IS NOT NEW.company_id
BEGIN SELECT RAISE(ABORT, 'currency belongs to another company'); END;

CREATE INDEX currency_rates_by_date ON currency_rates (company_id, currency_id, rate_date);

-- Existing companies get the usual currencies (names in the default interface language).
INSERT INTO currencies (company_id, code, name)
SELECT c.id, v.code, v.name
FROM companies c,
     (SELECT 'USD' AS code, 'ABŞ dolları' AS name
      UNION ALL SELECT 'EUR', 'Avro'
      UNION ALL SELECT 'RUB', 'Rusiya rublu'
      UNION ALL SELECT 'TRY', 'Türkiyə lirəsi'
      UNION ALL SELECT 'GBP', 'Britaniya funt sterlinqi') v;
