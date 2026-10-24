-- The view of 0032 with the module's own document (owner_id): the journal, the bank
-- statement and the main window learn from it which page opens a GL document, instead of
-- reading the modules' tables each in its own way (docs/ENGINEERING.md, debt 12).
--   owner_id: the warehouse document, the conversion, the bank operation; for 'uses' —
--   the warehouse document that takes the GL document in as an expense of its batch.
DROP VIEW document_owners;

CREATE VIEW document_owners AS
SELECT company_id, gl_document_id AS document_id, 'inventory' AS module, 'made' AS role,
       id AS owner_id, number AS owner_number
FROM inventory_documents WHERE gl_document_id IS NOT NULL
UNION ALL
SELECT company_id, accrual_document_id, 'inventory', 'made', id, number
FROM inventory_documents WHERE accrual_document_id IS NOT NULL
UNION ALL
SELECT company_id, document_id, 'conversion', 'made', id, NULL
FROM currency_conversions WHERE document_id IS NOT NULL
UNION ALL
SELECT company_id, credit_document_id, 'conversion', 'made', id, NULL
FROM currency_conversions WHERE credit_document_id IS NOT NULL
UNION ALL
SELECT company_id, document_id, 'bank', 'made', id, NULL
FROM bank_operations WHERE document_id IS NOT NULL
UNION ALL
SELECT c.company_id, c.source_document_id, 'landed_cost', 'uses', d.id, d.number
FROM landed_cost_charges c
JOIN inventory_documents d ON d.company_id = c.company_id AND d.id = c.document_id
WHERE c.source_document_id IS NOT NULL;
