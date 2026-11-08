-- One document in the user's eyes (D-new-one-document): a GL document a module made is
-- named by the module's document — «Alış №6», not «Sənəd №13». The view says what kind
-- of document it is; the core still reads only the view, never the modules' tables.
--   owner_kind: the inventory document's doc_type (an accrual — its purchase's or sale's),
--   'conversion', 'bank_in' / 'bank_out'; 'landed_cost' for the documents a charge uses.
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
SELECT company_id, document_id, 'bank', 'made', id, NULL, 'bank_' || direction
FROM bank_operations WHERE document_id IS NOT NULL
UNION ALL
SELECT c.company_id, c.source_document_id, 'landed_cost', 'uses', d.id, d.number, 'landed_cost'
FROM landed_cost_charges c
JOIN inventory_documents d ON d.company_id = c.company_id AND d.id = c.document_id
WHERE c.source_document_id IS NOT NULL;
