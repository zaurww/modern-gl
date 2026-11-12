-- The cash desk in the bank module: an operation on a cash account (type 'cash', 50) is
-- a cash order — «Kassa mədaxil orderi», «Kassa məxaric orderi» — not «Bank mədaxili».
--   owner_kind: as 0068, and 'cash_in' / 'cash_out' for the operations of a cash desk.
DROP VIEW document_owners;

CREATE VIEW document_owners AS
SELECT company_id, gl_document_id AS document_id, 'inventory' AS module, 'made' AS role,
       id AS owner_id, number AS owner_number, doc_type AS owner_kind
FROM inventory_documents WHERE gl_document_id IS NOT NULL
UNION ALL
SELECT a.company_id, a.gl_document_id, 'inventory', 'made', d.id, d.number, d.doc_type
FROM inventory_accruals a
JOIN inventory_documents d ON d.company_id = a.company_id AND d.id = a.document_id
UNION ALL
SELECT company_id, document_id, 'conversion', 'made', id, NULL, 'conversion'
FROM currency_conversions WHERE document_id IS NOT NULL
UNION ALL
SELECT company_id, credit_document_id, 'conversion', 'made', id, NULL, 'conversion'
FROM currency_conversions WHERE credit_document_id IS NOT NULL
UNION ALL
SELECT o.company_id, o.document_id, 'bank', 'made', o.id, NULL,
       CASE WHEN a.account_type = 'cash' THEN 'cash_' ELSE 'bank_' END || o.direction
FROM bank_operations o
LEFT JOIN accounts a ON a.company_id = o.company_id AND a.id = o.account_id
WHERE o.document_id IS NOT NULL
UNION ALL
SELECT c.company_id, c.source_document_id, 'landed_cost', 'uses', d.id, d.number, 'landed_cost'
FROM landed_cost_charges c
JOIN inventory_documents d ON d.company_id = c.company_id AND d.id = c.document_id
WHERE c.source_document_id IS NOT NULL;
