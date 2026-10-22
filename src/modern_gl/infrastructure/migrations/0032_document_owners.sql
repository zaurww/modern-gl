-- Who owns a GL document a module made, and which GL documents a module takes in
-- (docs/ENGINEERING.md, debt 1). The core reads this view only, never the modules'
-- tables, so a module's postings are protected whatever code is loaded. A module that
-- links GL documents adds itself here in a migration of its own (DROP VIEW, CREATE VIEW).
--   role 'made': the module wrote the document; it is corrected there.
--   role 'uses': the module takes the document in; it must be released there first.
CREATE VIEW document_owners AS
SELECT company_id, gl_document_id AS document_id, 'inventory' AS module, 'made' AS role,
       number AS owner_number
FROM inventory_documents WHERE gl_document_id IS NOT NULL
UNION ALL
SELECT company_id, accrual_document_id, 'inventory', 'made', number
FROM inventory_documents WHERE accrual_document_id IS NOT NULL
UNION ALL
SELECT company_id, document_id, 'conversion', 'made', NULL
FROM currency_conversions WHERE document_id IS NOT NULL
UNION ALL
SELECT company_id, credit_document_id, 'conversion', 'made', NULL
FROM currency_conversions WHERE credit_document_id IS NOT NULL
UNION ALL
SELECT company_id, document_id, 'bank', 'made', NULL
FROM bank_operations WHERE document_id IS NOT NULL
UNION ALL
SELECT c.company_id, c.source_document_id, 'landed_cost', 'uses', d.number
FROM landed_cost_charges c
JOIN inventory_documents d ON d.company_id = c.company_id AND d.id = c.document_id
WHERE c.source_document_id IS NOT NULL;
