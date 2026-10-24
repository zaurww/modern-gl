-- Who the counterparty of a purchase or sale line is: an element of the kind
-- 'counterparty' among the subconto of its settlement side (offset_sc1..3), whatever its
-- place there (debt 12). One rule for the purchase list, the stock card, the declarations
-- report, the e-qaimə import and batch posting; the counterparty of a document is that of
-- its first line (line_no).
CREATE VIEW inventory_line_counterparties AS
SELECT l.company_id, l.document_id, l.id AS line_id, l.line_no,
       v.id AS counterparty_id, v.name, v.tax_id
FROM inventory_lines l
JOIN subconto_values v
  ON v.company_id = l.company_id AND v.id IN (l.offset_sc1, l.offset_sc2, l.offset_sc3)
JOIN subconto_kinds k
  ON k.company_id = v.company_id AND k.id = v.kind_id AND k.code = 'counterparty';
