-- The rules the code keeps, kept by the file too (D149): a mistake of the code, an
-- import or a tool that writes to the file directly is refused, not stored.
--
-- 1. An INTEGER column holds an integer (or NULL): SQLite would keep 12.5 or '12,5' there
--    and every sum would go on with it. On an update only a changed value is checked, so
--    a row written before stays editable.
-- 2. The closed period (companies.closed_through) as `require_open` keeps it: a document
--    dated in it is not posted, a posted one in it is neither unposted nor changed — for
--    GL documents and for warehouse documents.
-- 3. The rows a module builds a posted GL document of the closed period from do not change
--    (bank operations and their lines, currency conversions and their fees, the accruals of
--    a receipt). What does not make postings stays free: the statement's reference, the
--    second document of a conversion.


-- 1. integers --------------------------------------------------------------------

CREATE TRIGGER account_roles_integers_insert BEFORE INSERT ON account_roles
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'account_roles: not an integer'); END;

CREATE TRIGGER account_roles_integers_update BEFORE UPDATE ON account_roles
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'account_roles: not an integer'); END;

CREATE TRIGGER accounts_integers_insert BEFORE INSERT ON accounts
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.parent_id) NOT IN ('integer', 'null')
   OR typeof(NEW.is_group) NOT IN ('integer', 'null')
   OR typeof(NEW.active) NOT IN ('integer', 'null')
   OR typeof(NEW.sc1_kind_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc2_kind_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc3_kind_id) NOT IN ('integer', 'null')
   OR typeof(NEW.contra) NOT IN ('integer', 'null')
   OR typeof(NEW.two_sided) NOT IN ('integer', 'null')
   OR typeof(NEW.currency) NOT IN ('integer', 'null')
   OR typeof(NEW.sc_optional) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'accounts: not an integer'); END;

CREATE TRIGGER accounts_integers_update BEFORE UPDATE ON accounts
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.parent_id IS NOT OLD.parent_id AND typeof(NEW.parent_id) NOT IN ('integer', 'null'))
   OR (NEW.is_group IS NOT OLD.is_group AND typeof(NEW.is_group) NOT IN ('integer', 'null'))
   OR (NEW.active IS NOT OLD.active AND typeof(NEW.active) NOT IN ('integer', 'null'))
   OR (NEW.sc1_kind_id IS NOT OLD.sc1_kind_id AND typeof(NEW.sc1_kind_id) NOT IN ('integer', 'null'))
   OR (NEW.sc2_kind_id IS NOT OLD.sc2_kind_id AND typeof(NEW.sc2_kind_id) NOT IN ('integer', 'null'))
   OR (NEW.sc3_kind_id IS NOT OLD.sc3_kind_id AND typeof(NEW.sc3_kind_id) NOT IN ('integer', 'null'))
   OR (NEW.contra IS NOT OLD.contra AND typeof(NEW.contra) NOT IN ('integer', 'null'))
   OR (NEW.two_sided IS NOT OLD.two_sided AND typeof(NEW.two_sided) NOT IN ('integer', 'null'))
   OR (NEW.currency IS NOT OLD.currency AND typeof(NEW.currency) NOT IN ('integer', 'null'))
   OR (NEW.sc_optional IS NOT OLD.sc_optional AND typeof(NEW.sc_optional) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'accounts: not an integer'); END;

CREATE TRIGGER audit_events_integers_insert BEFORE INSERT ON audit_events
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.entity_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'audit_events: not an integer'); END;

CREATE TRIGGER bank_account_details_integers_insert BEFORE INSERT ON bank_account_details
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.value_id) NOT IN ('integer', 'null')
   OR typeof(NEW.holder_id) NOT IN ('integer', 'null')
   OR typeof(NEW.closed) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'bank_account_details: not an integer'); END;

CREATE TRIGGER bank_account_details_integers_update BEFORE UPDATE ON bank_account_details
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.value_id IS NOT OLD.value_id AND typeof(NEW.value_id) NOT IN ('integer', 'null'))
   OR (NEW.holder_id IS NOT OLD.holder_id AND typeof(NEW.holder_id) NOT IN ('integer', 'null'))
   OR (NEW.closed IS NOT OLD.closed AND typeof(NEW.closed) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'bank_account_details: not an integer'); END;

CREATE TRIGGER bank_operation_lines_integers_insert BEFORE INSERT ON bank_operation_lines
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.operation_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
   OR typeof(NEW.pays_vat) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'bank_operation_lines: not an integer'); END;

CREATE TRIGGER bank_operation_lines_integers_update BEFORE UPDATE ON bank_operation_lines
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.operation_id IS NOT OLD.operation_id AND typeof(NEW.operation_id) NOT IN ('integer', 'null'))
   OR (NEW.line_no IS NOT OLD.line_no AND typeof(NEW.line_no) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.sc1 IS NOT OLD.sc1 AND typeof(NEW.sc1) NOT IN ('integer', 'null'))
   OR (NEW.sc2 IS NOT OLD.sc2 AND typeof(NEW.sc2) NOT IN ('integer', 'null'))
   OR (NEW.sc3 IS NOT OLD.sc3 AND typeof(NEW.sc3) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
   OR (NEW.pays_vat IS NOT OLD.pays_vat AND typeof(NEW.pays_vat) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'bank_operation_lines: not an integer'); END;

CREATE TRIGGER bank_operations_integers_insert BEFORE INSERT ON bank_operations
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.counterparty_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'bank_operations: not an integer'); END;

CREATE TRIGGER bank_operations_integers_update BEFORE UPDATE ON bank_operations
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.sc1 IS NOT OLD.sc1 AND typeof(NEW.sc1) NOT IN ('integer', 'null'))
   OR (NEW.sc2 IS NOT OLD.sc2 AND typeof(NEW.sc2) NOT IN ('integer', 'null'))
   OR (NEW.sc3 IS NOT OLD.sc3 AND typeof(NEW.sc3) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.counterparty_id IS NOT OLD.counterparty_id AND typeof(NEW.counterparty_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'bank_operations: not an integer'); END;

CREATE TRIGGER bank_portal_loads_integers_insert BEFORE INSERT ON bank_portal_loads
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.value_id) NOT IN ('integer', 'null')
   OR typeof(NEW.operations) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'bank_portal_loads: not an integer'); END;

CREATE TRIGGER bank_portal_loads_integers_update BEFORE UPDATE ON bank_portal_loads
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.value_id IS NOT OLD.value_id AND typeof(NEW.value_id) NOT IN ('integer', 'null'))
   OR (NEW.operations IS NOT OLD.operations AND typeof(NEW.operations) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'bank_portal_loads: not an integer'); END;

CREATE TRIGGER bank_portal_reconciled_integers_insert BEFORE INSERT ON bank_portal_reconciled
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.value_id) NOT IN ('integer', 'null')
   OR typeof(NEW.portal_opening) NOT IN ('integer', 'null')
   OR typeof(NEW.portal_in) NOT IN ('integer', 'null')
   OR typeof(NEW.portal_out) NOT IN ('integer', 'null')
   OR typeof(NEW.books_opening) NOT IN ('integer', 'null')
   OR typeof(NEW.books_in) NOT IN ('integer', 'null')
   OR typeof(NEW.books_out) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'bank_portal_reconciled: not an integer'); END;

CREATE TRIGGER bank_portal_reconciled_integers_update BEFORE UPDATE ON bank_portal_reconciled
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.value_id IS NOT OLD.value_id AND typeof(NEW.value_id) NOT IN ('integer', 'null'))
   OR (NEW.portal_opening IS NOT OLD.portal_opening AND typeof(NEW.portal_opening) NOT IN ('integer', 'null'))
   OR (NEW.portal_in IS NOT OLD.portal_in AND typeof(NEW.portal_in) NOT IN ('integer', 'null'))
   OR (NEW.portal_out IS NOT OLD.portal_out AND typeof(NEW.portal_out) NOT IN ('integer', 'null'))
   OR (NEW.books_opening IS NOT OLD.books_opening AND typeof(NEW.books_opening) NOT IN ('integer', 'null'))
   OR (NEW.books_in IS NOT OLD.books_in AND typeof(NEW.books_in) NOT IN ('integer', 'null'))
   OR (NEW.books_out IS NOT OLD.books_out AND typeof(NEW.books_out) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'bank_portal_reconciled: not an integer'); END;

CREATE TRIGGER bank_statements_integers_insert BEFORE INSERT ON bank_statements
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.value_id) NOT IN ('integer', 'null')
   OR typeof(NEW.bank_closing) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'bank_statements: not an integer'); END;

CREATE TRIGGER bank_statements_integers_update BEFORE UPDATE ON bank_statements
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.value_id IS NOT OLD.value_id AND typeof(NEW.value_id) NOT IN ('integer', 'null'))
   OR (NEW.bank_closing IS NOT OLD.bank_closing AND typeof(NEW.bank_closing) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'bank_statements: not an integer'); END;

CREATE TRIGGER companies_integers_insert BEFORE INSERT ON companies
WHEN typeof(NEW.last_number) NOT IN ('integer', 'null')
   OR typeof(NEW.last_inventory_number) NOT IN ('integer', 'null')
   OR typeof(NEW.parallel_books) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'companies: not an integer'); END;

CREATE TRIGGER companies_integers_update BEFORE UPDATE ON companies
WHEN (NEW.last_number IS NOT OLD.last_number AND typeof(NEW.last_number) NOT IN ('integer', 'null'))
   OR (NEW.last_inventory_number IS NOT OLD.last_inventory_number AND typeof(NEW.last_inventory_number) NOT IN ('integer', 'null'))
   OR (NEW.parallel_books IS NOT OLD.parallel_books AND typeof(NEW.parallel_books) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'companies: not an integer'); END;

CREATE TRIGGER conversion_fees_integers_insert BEFORE INSERT ON conversion_fees
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.conversion_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
   OR typeof(NEW.expense_account_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'conversion_fees: not an integer'); END;

CREATE TRIGGER conversion_fees_integers_update BEFORE UPDATE ON conversion_fees
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.conversion_id IS NOT OLD.conversion_id AND typeof(NEW.conversion_id) NOT IN ('integer', 'null'))
   OR (NEW.line_no IS NOT OLD.line_no AND typeof(NEW.line_no) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.sc1 IS NOT OLD.sc1 AND typeof(NEW.sc1) NOT IN ('integer', 'null'))
   OR (NEW.sc2 IS NOT OLD.sc2 AND typeof(NEW.sc2) NOT IN ('integer', 'null'))
   OR (NEW.sc3 IS NOT OLD.sc3 AND typeof(NEW.sc3) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
   OR (NEW.expense_account_id IS NOT OLD.expense_account_id AND typeof(NEW.expense_account_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'conversion_fees: not an integer'); END;

CREATE TRIGGER currencies_integers_insert BEFORE INSERT ON currencies
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.active) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'currencies: not an integer'); END;

CREATE TRIGGER currencies_integers_update BEFORE UPDATE ON currencies
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.active IS NOT OLD.active AND typeof(NEW.active) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'currencies: not an integer'); END;

CREATE TRIGGER currency_conversions_integers_insert BEFORE INSERT ON currency_conversions
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.credit_document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.from_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.from_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.from_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.from_sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.from_currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.from_amount) NOT IN ('integer', 'null')
   OR typeof(NEW.to_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.to_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.to_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.to_sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.to_currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.to_amount) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'currency_conversions: not an integer'); END;

CREATE TRIGGER currency_conversions_integers_update BEFORE UPDATE ON currency_conversions
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.credit_document_id IS NOT OLD.credit_document_id AND typeof(NEW.credit_document_id) NOT IN ('integer', 'null'))
   OR (NEW.from_account_id IS NOT OLD.from_account_id AND typeof(NEW.from_account_id) NOT IN ('integer', 'null'))
   OR (NEW.from_sc1 IS NOT OLD.from_sc1 AND typeof(NEW.from_sc1) NOT IN ('integer', 'null'))
   OR (NEW.from_sc2 IS NOT OLD.from_sc2 AND typeof(NEW.from_sc2) NOT IN ('integer', 'null'))
   OR (NEW.from_sc3 IS NOT OLD.from_sc3 AND typeof(NEW.from_sc3) NOT IN ('integer', 'null'))
   OR (NEW.from_currency_id IS NOT OLD.from_currency_id AND typeof(NEW.from_currency_id) NOT IN ('integer', 'null'))
   OR (NEW.from_amount IS NOT OLD.from_amount AND typeof(NEW.from_amount) NOT IN ('integer', 'null'))
   OR (NEW.to_account_id IS NOT OLD.to_account_id AND typeof(NEW.to_account_id) NOT IN ('integer', 'null'))
   OR (NEW.to_sc1 IS NOT OLD.to_sc1 AND typeof(NEW.to_sc1) NOT IN ('integer', 'null'))
   OR (NEW.to_sc2 IS NOT OLD.to_sc2 AND typeof(NEW.to_sc2) NOT IN ('integer', 'null'))
   OR (NEW.to_sc3 IS NOT OLD.to_sc3 AND typeof(NEW.to_sc3) NOT IN ('integer', 'null'))
   OR (NEW.to_currency_id IS NOT OLD.to_currency_id AND typeof(NEW.to_currency_id) NOT IN ('integer', 'null'))
   OR (NEW.to_amount IS NOT OLD.to_amount AND typeof(NEW.to_amount) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'currency_conversions: not an integer'); END;

CREATE TRIGGER currency_rates_integers_insert BEFORE INSERT ON currency_rates
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.rate) NOT IN ('integer', 'null')
   OR typeof(NEW.nominal) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'currency_rates: not an integer'); END;

CREATE TRIGGER currency_rates_integers_update BEFORE UPDATE ON currency_rates
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.rate IS NOT OLD.rate AND typeof(NEW.rate) NOT IN ('integer', 'null'))
   OR (NEW.nominal IS NOT OLD.nominal AND typeof(NEW.nominal) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'currency_rates: not an integer'); END;

CREATE TRIGGER document_sources_integers_insert BEFORE INSERT ON document_sources
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'document_sources: not an integer'); END;

CREATE TRIGGER document_sources_integers_update BEFORE UPDATE ON document_sources
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'document_sources: not an integer'); END;

CREATE TRIGGER documents_integers_insert BEFORE INSERT ON documents
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.number) NOT IN ('integer', 'null')
   OR typeof(NEW.layer_id) NOT IN ('integer', 'null')
   OR typeof(NEW.reversal_of) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'documents: not an integer'); END;

CREATE TRIGGER documents_integers_update BEFORE UPDATE ON documents
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.number IS NOT OLD.number AND typeof(NEW.number) NOT IN ('integer', 'null'))
   OR (NEW.layer_id IS NOT OLD.layer_id AND typeof(NEW.layer_id) NOT IN ('integer', 'null'))
   OR (NEW.reversal_of IS NOT OLD.reversal_of AND typeof(NEW.reversal_of) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'documents: not an integer'); END;

CREATE TRIGGER entry_template_lines_integers_insert BEFORE INSERT ON entry_template_lines
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.template_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.debit_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.credit_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc3) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'entry_template_lines: not an integer'); END;

CREATE TRIGGER entry_template_lines_integers_update BEFORE UPDATE ON entry_template_lines
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.template_id IS NOT OLD.template_id AND typeof(NEW.template_id) NOT IN ('integer', 'null'))
   OR (NEW.line_no IS NOT OLD.line_no AND typeof(NEW.line_no) NOT IN ('integer', 'null'))
   OR (NEW.debit_account_id IS NOT OLD.debit_account_id AND typeof(NEW.debit_account_id) NOT IN ('integer', 'null'))
   OR (NEW.credit_account_id IS NOT OLD.credit_account_id AND typeof(NEW.credit_account_id) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc1 IS NOT OLD.dt_sc1 AND typeof(NEW.dt_sc1) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc2 IS NOT OLD.dt_sc2 AND typeof(NEW.dt_sc2) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc3 IS NOT OLD.dt_sc3 AND typeof(NEW.dt_sc3) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc1 IS NOT OLD.ct_sc1 AND typeof(NEW.ct_sc1) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc2 IS NOT OLD.ct_sc2 AND typeof(NEW.ct_sc2) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc3 IS NOT OLD.ct_sc3 AND typeof(NEW.ct_sc3) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'entry_template_lines: not an integer'); END;

CREATE TRIGGER entry_templates_integers_insert BEFORE INSERT ON entry_templates
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'entry_templates: not an integer'); END;

CREATE TRIGGER entry_templates_integers_update BEFORE UPDATE ON entry_templates
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'entry_templates: not an integer'); END;

CREATE TRIGGER eqaime_portal_integers_insert BEFORE INSERT ON eqaime_portal
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.outgoing) NOT IN ('integer', 'null')
   OR typeof(NEW.total) NOT IN ('integer', 'null')
   OR typeof(NEW.vat) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'eqaime_portal: not an integer'); END;

CREATE TRIGGER eqaime_portal_integers_update BEFORE UPDATE ON eqaime_portal
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.outgoing IS NOT OLD.outgoing AND typeof(NEW.outgoing) NOT IN ('integer', 'null'))
   OR (NEW.total IS NOT OLD.total AND typeof(NEW.total) NOT IN ('integer', 'null'))
   OR (NEW.vat IS NOT OLD.vat AND typeof(NEW.vat) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'eqaime_portal: not an integer'); END;

CREATE TRIGGER eqaime_portal_changes_integers_insert BEFORE INSERT ON eqaime_portal_changes
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.portal_id) NOT IN ('integer', 'null')
   OR typeof(NEW.old_total) NOT IN ('integer', 'null')
   OR typeof(NEW.new_total) NOT IN ('integer', 'null')
   OR typeof(NEW.old_vat) NOT IN ('integer', 'null')
   OR typeof(NEW.new_vat) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'eqaime_portal_changes: not an integer'); END;

CREATE TRIGGER eqaime_portal_changes_integers_update BEFORE UPDATE ON eqaime_portal_changes
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.portal_id IS NOT OLD.portal_id AND typeof(NEW.portal_id) NOT IN ('integer', 'null'))
   OR (NEW.old_total IS NOT OLD.old_total AND typeof(NEW.old_total) NOT IN ('integer', 'null'))
   OR (NEW.new_total IS NOT OLD.new_total AND typeof(NEW.new_total) NOT IN ('integer', 'null'))
   OR (NEW.old_vat IS NOT OLD.old_vat AND typeof(NEW.old_vat) NOT IN ('integer', 'null'))
   OR (NEW.new_vat IS NOT OLD.new_vat AND typeof(NEW.new_vat) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'eqaime_portal_changes: not an integer'); END;

CREATE TRIGGER eqaime_reconciled_integers_insert BEFORE INSERT ON eqaime_reconciled
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.outgoing) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'eqaime_reconciled: not an integer'); END;

CREATE TRIGGER eqaime_reconciled_integers_update BEFORE UPDATE ON eqaime_reconciled
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.outgoing IS NOT OLD.outgoing AND typeof(NEW.outgoing) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'eqaime_reconciled: not an integer'); END;

CREATE TRIGGER inventory_accruals_integers_insert BEFORE INSERT ON inventory_accruals
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.gl_document_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_accruals: not an integer'); END;

CREATE TRIGGER inventory_accruals_integers_update BEFORE UPDATE ON inventory_accruals
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.gl_document_id IS NOT OLD.gl_document_id AND typeof(NEW.gl_document_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_accruals: not an integer'); END;

CREATE TRIGGER inventory_documents_integers_insert BEFORE INSERT ON inventory_documents
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.number) NOT IN ('integer', 'null')
   OR typeof(NEW.landed_cost_type_id) NOT IN ('integer', 'null')
   OR typeof(NEW.gl_document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.vat_rate) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_rate) NOT IN ('integer', 'null')
   OR typeof(NEW.awaits_invoice) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_documents: not an integer'); END;

CREATE TRIGGER inventory_documents_integers_update BEFORE UPDATE ON inventory_documents
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.number IS NOT OLD.number AND typeof(NEW.number) NOT IN ('integer', 'null'))
   OR (NEW.landed_cost_type_id IS NOT OLD.landed_cost_type_id AND typeof(NEW.landed_cost_type_id) NOT IN ('integer', 'null'))
   OR (NEW.gl_document_id IS NOT OLD.gl_document_id AND typeof(NEW.gl_document_id) NOT IN ('integer', 'null'))
   OR (NEW.vat_rate IS NOT OLD.vat_rate AND typeof(NEW.vat_rate) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.currency_rate IS NOT OLD.currency_rate AND typeof(NEW.currency_rate) NOT IN ('integer', 'null'))
   OR (NEW.awaits_invoice IS NOT OLD.awaits_invoice AND typeof(NEW.awaits_invoice) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_documents: not an integer'); END;

CREATE TRIGGER inventory_items_integers_insert BEFORE INSERT ON inventory_items
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.subconto_value_id) NOT IN ('integer', 'null')
   OR typeof(NEW.unit_id) NOT IN ('integer', 'null')
   OR typeof(NEW.inventory_account_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_items: not an integer'); END;

CREATE TRIGGER inventory_items_integers_update BEFORE UPDATE ON inventory_items
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.subconto_value_id IS NOT OLD.subconto_value_id AND typeof(NEW.subconto_value_id) NOT IN ('integer', 'null'))
   OR (NEW.unit_id IS NOT OLD.unit_id AND typeof(NEW.unit_id) NOT IN ('integer', 'null'))
   OR (NEW.inventory_account_id IS NOT OLD.inventory_account_id AND typeof(NEW.inventory_account_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_items: not an integer'); END;

CREATE TRIGGER inventory_lines_integers_insert BEFORE INSERT ON inventory_lines
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.item_id) NOT IN ('integer', 'null')
   OR typeof(NEW.warehouse_id) NOT IN ('integer', 'null')
   OR typeof(NEW.to_warehouse_id) NOT IN ('integer', 'null')
   OR typeof(NEW.quantity) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
   OR typeof(NEW.inventory_amount) NOT IN ('integer', 'null')
   OR typeof(NEW.expense_amount) NOT IN ('integer', 'null')
   OR typeof(NEW.offset_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.offset_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.offset_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.offset_sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.source_receipt_line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.vat_amount) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_amount) NOT IN ('integer', 'null')
   OR typeof(NEW.cost_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.cost_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.cost_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.cost_sc3) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_lines: not an integer'); END;

CREATE TRIGGER inventory_lines_integers_update BEFORE UPDATE ON inventory_lines
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.line_no IS NOT OLD.line_no AND typeof(NEW.line_no) NOT IN ('integer', 'null'))
   OR (NEW.item_id IS NOT OLD.item_id AND typeof(NEW.item_id) NOT IN ('integer', 'null'))
   OR (NEW.warehouse_id IS NOT OLD.warehouse_id AND typeof(NEW.warehouse_id) NOT IN ('integer', 'null'))
   OR (NEW.to_warehouse_id IS NOT OLD.to_warehouse_id AND typeof(NEW.to_warehouse_id) NOT IN ('integer', 'null'))
   OR (NEW.quantity IS NOT OLD.quantity AND typeof(NEW.quantity) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
   OR (NEW.inventory_amount IS NOT OLD.inventory_amount AND typeof(NEW.inventory_amount) NOT IN ('integer', 'null'))
   OR (NEW.expense_amount IS NOT OLD.expense_amount AND typeof(NEW.expense_amount) NOT IN ('integer', 'null'))
   OR (NEW.offset_account_id IS NOT OLD.offset_account_id AND typeof(NEW.offset_account_id) NOT IN ('integer', 'null'))
   OR (NEW.offset_sc1 IS NOT OLD.offset_sc1 AND typeof(NEW.offset_sc1) NOT IN ('integer', 'null'))
   OR (NEW.offset_sc2 IS NOT OLD.offset_sc2 AND typeof(NEW.offset_sc2) NOT IN ('integer', 'null'))
   OR (NEW.offset_sc3 IS NOT OLD.offset_sc3 AND typeof(NEW.offset_sc3) NOT IN ('integer', 'null'))
   OR (NEW.source_receipt_line_id IS NOT OLD.source_receipt_line_id AND typeof(NEW.source_receipt_line_id) NOT IN ('integer', 'null'))
   OR (NEW.vat_amount IS NOT OLD.vat_amount AND typeof(NEW.vat_amount) NOT IN ('integer', 'null'))
   OR (NEW.currency_amount IS NOT OLD.currency_amount AND typeof(NEW.currency_amount) NOT IN ('integer', 'null'))
   OR (NEW.cost_account_id IS NOT OLD.cost_account_id AND typeof(NEW.cost_account_id) NOT IN ('integer', 'null'))
   OR (NEW.cost_sc1 IS NOT OLD.cost_sc1 AND typeof(NEW.cost_sc1) NOT IN ('integer', 'null'))
   OR (NEW.cost_sc2 IS NOT OLD.cost_sc2 AND typeof(NEW.cost_sc2) NOT IN ('integer', 'null'))
   OR (NEW.cost_sc3 IS NOT OLD.cost_sc3 AND typeof(NEW.cost_sc3) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_lines: not an integer'); END;

CREATE TRIGGER inventory_units_integers_insert BEFORE INSERT ON inventory_units
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.precision) NOT IN ('integer', 'null')
   OR typeof(NEW.active) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'inventory_units: not an integer'); END;

CREATE TRIGGER inventory_units_integers_update BEFORE UPDATE ON inventory_units
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.precision IS NOT OLD.precision AND typeof(NEW.precision) NOT IN ('integer', 'null'))
   OR (NEW.active IS NOT OLD.active AND typeof(NEW.active) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'inventory_units: not an integer'); END;

CREATE TRIGGER landed_cost_charges_integers_insert BEFORE INSERT ON landed_cost_charges
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.cost_type_id) NOT IN ('integer', 'null')
   OR typeof(NEW.account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
   OR typeof(NEW.vat_amount) NOT IN ('integer', 'null')
   OR typeof(NEW.source_document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.source_line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_rate) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_amount) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'landed_cost_charges: not an integer'); END;

CREATE TRIGGER landed_cost_charges_integers_update BEFORE UPDATE ON landed_cost_charges
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.line_no IS NOT OLD.line_no AND typeof(NEW.line_no) NOT IN ('integer', 'null'))
   OR (NEW.cost_type_id IS NOT OLD.cost_type_id AND typeof(NEW.cost_type_id) NOT IN ('integer', 'null'))
   OR (NEW.account_id IS NOT OLD.account_id AND typeof(NEW.account_id) NOT IN ('integer', 'null'))
   OR (NEW.sc1 IS NOT OLD.sc1 AND typeof(NEW.sc1) NOT IN ('integer', 'null'))
   OR (NEW.sc2 IS NOT OLD.sc2 AND typeof(NEW.sc2) NOT IN ('integer', 'null'))
   OR (NEW.sc3 IS NOT OLD.sc3 AND typeof(NEW.sc3) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
   OR (NEW.vat_amount IS NOT OLD.vat_amount AND typeof(NEW.vat_amount) NOT IN ('integer', 'null'))
   OR (NEW.source_document_id IS NOT OLD.source_document_id AND typeof(NEW.source_document_id) NOT IN ('integer', 'null'))
   OR (NEW.source_line_no IS NOT OLD.source_line_no AND typeof(NEW.source_line_no) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.currency_rate IS NOT OLD.currency_rate AND typeof(NEW.currency_rate) NOT IN ('integer', 'null'))
   OR (NEW.currency_amount IS NOT OLD.currency_amount AND typeof(NEW.currency_amount) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'landed_cost_charges: not an integer'); END;

CREATE TRIGGER landed_cost_expense_allocations_integers_insert BEFORE INSERT ON landed_cost_expense_allocations
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.landed_cost_line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.issue_line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'landed_cost_expense_allocations: not an integer'); END;

CREATE TRIGGER landed_cost_expense_allocations_integers_update BEFORE UPDATE ON landed_cost_expense_allocations
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.landed_cost_line_id IS NOT OLD.landed_cost_line_id AND typeof(NEW.landed_cost_line_id) NOT IN ('integer', 'null'))
   OR (NEW.issue_line_id IS NOT OLD.issue_line_id AND typeof(NEW.issue_line_id) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'landed_cost_expense_allocations: not an integer'); END;

CREATE TRIGGER landed_cost_shares_integers_insert BEFORE INSERT ON landed_cost_shares
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.charge_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'landed_cost_shares: not an integer'); END;

CREATE TRIGGER landed_cost_shares_integers_update BEFORE UPDATE ON landed_cost_shares
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.charge_id IS NOT OLD.charge_id AND typeof(NEW.charge_id) NOT IN ('integer', 'null'))
   OR (NEW.line_id IS NOT OLD.line_id AND typeof(NEW.line_id) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'landed_cost_shares: not an integer'); END;

CREATE TRIGGER landed_cost_types_integers_insert BEFORE INSERT ON landed_cost_types
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.active) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'landed_cost_types: not an integer'); END;

CREATE TRIGGER landed_cost_types_integers_update BEFORE UPDATE ON landed_cost_types
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.active IS NOT OLD.active AND typeof(NEW.active) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'landed_cost_types: not an integer'); END;

CREATE TRIGGER layers_integers_insert BEFORE INSERT ON layers
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'layers: not an integer'); END;

CREATE TRIGGER layers_integers_update BEFORE UPDATE ON layers
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'layers: not an integer'); END;

CREATE TRIGGER opening_balance_documents_integers_insert BEFORE INSERT ON opening_balance_documents
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'opening_balance_documents: not an integer'); END;

CREATE TRIGGER opening_balance_documents_integers_update BEFORE UPDATE ON opening_balance_documents
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'opening_balance_documents: not an integer'); END;

CREATE TRIGGER postings_integers_insert BEFORE INSERT ON postings
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_no) NOT IN ('integer', 'null')
   OR typeof(NEW.debit_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.credit_account_id) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.dt_sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc1) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc2) NOT IN ('integer', 'null')
   OR typeof(NEW.ct_sc3) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_amount) NOT IN ('integer', 'null')
   OR typeof(NEW.pays_vat) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'postings: not an integer'); END;

CREATE TRIGGER postings_integers_update BEFORE UPDATE ON postings
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.line_no IS NOT OLD.line_no AND typeof(NEW.line_no) NOT IN ('integer', 'null'))
   OR (NEW.debit_account_id IS NOT OLD.debit_account_id AND typeof(NEW.debit_account_id) NOT IN ('integer', 'null'))
   OR (NEW.credit_account_id IS NOT OLD.credit_account_id AND typeof(NEW.credit_account_id) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc1 IS NOT OLD.dt_sc1 AND typeof(NEW.dt_sc1) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc2 IS NOT OLD.dt_sc2 AND typeof(NEW.dt_sc2) NOT IN ('integer', 'null'))
   OR (NEW.dt_sc3 IS NOT OLD.dt_sc3 AND typeof(NEW.dt_sc3) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc1 IS NOT OLD.ct_sc1 AND typeof(NEW.ct_sc1) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc2 IS NOT OLD.ct_sc2 AND typeof(NEW.ct_sc2) NOT IN ('integer', 'null'))
   OR (NEW.ct_sc3 IS NOT OLD.ct_sc3 AND typeof(NEW.ct_sc3) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.currency_amount IS NOT OLD.currency_amount AND typeof(NEW.currency_amount) NOT IN ('integer', 'null'))
   OR (NEW.pays_vat IS NOT OLD.pays_vat AND typeof(NEW.pays_vat) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'postings: not an integer'); END;

CREATE TRIGGER stock_consumptions_integers_insert BEFORE INSERT ON stock_consumptions
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.issue_line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.receipt_line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.quantity) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'stock_consumptions: not an integer'); END;

CREATE TRIGGER stock_consumptions_integers_update BEFORE UPDATE ON stock_consumptions
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.issue_line_id IS NOT OLD.issue_line_id AND typeof(NEW.issue_line_id) NOT IN ('integer', 'null'))
   OR (NEW.receipt_line_id IS NOT OLD.receipt_line_id AND typeof(NEW.receipt_line_id) NOT IN ('integer', 'null'))
   OR (NEW.quantity IS NOT OLD.quantity AND typeof(NEW.quantity) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'stock_consumptions: not an integer'); END;

CREATE TRIGGER stock_movements_integers_insert BEFORE INSERT ON stock_movements
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.document_id) NOT IN ('integer', 'null')
   OR typeof(NEW.line_id) NOT IN ('integer', 'null')
   OR typeof(NEW.item_id) NOT IN ('integer', 'null')
   OR typeof(NEW.warehouse_id) NOT IN ('integer', 'null')
   OR typeof(NEW.quantity) NOT IN ('integer', 'null')
   OR typeof(NEW.amount) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'stock_movements: not an integer'); END;

CREATE TRIGGER stock_movements_integers_update BEFORE UPDATE ON stock_movements
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.document_id IS NOT OLD.document_id AND typeof(NEW.document_id) NOT IN ('integer', 'null'))
   OR (NEW.line_id IS NOT OLD.line_id AND typeof(NEW.line_id) NOT IN ('integer', 'null'))
   OR (NEW.item_id IS NOT OLD.item_id AND typeof(NEW.item_id) NOT IN ('integer', 'null'))
   OR (NEW.warehouse_id IS NOT OLD.warehouse_id AND typeof(NEW.warehouse_id) NOT IN ('integer', 'null'))
   OR (NEW.quantity IS NOT OLD.quantity AND typeof(NEW.quantity) NOT IN ('integer', 'null'))
   OR (NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'stock_movements: not an integer'); END;

CREATE TRIGGER subconto_kinds_integers_insert BEFORE INSERT ON subconto_kinds
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.owner_kind_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'subconto_kinds: not an integer'); END;

CREATE TRIGGER subconto_kinds_integers_update BEFORE UPDATE ON subconto_kinds
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.owner_kind_id IS NOT OLD.owner_kind_id AND typeof(NEW.owner_kind_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'subconto_kinds: not an integer'); END;

CREATE TRIGGER subconto_value_tags_integers_insert BEFORE INSERT ON subconto_value_tags
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.value_id) NOT IN ('integer', 'null')
   OR typeof(NEW.tag_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'subconto_value_tags: not an integer'); END;

CREATE TRIGGER subconto_value_tags_integers_update BEFORE UPDATE ON subconto_value_tags
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.value_id IS NOT OLD.value_id AND typeof(NEW.value_id) NOT IN ('integer', 'null'))
   OR (NEW.tag_id IS NOT OLD.tag_id AND typeof(NEW.tag_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'subconto_value_tags: not an integer'); END;

CREATE TRIGGER subconto_values_integers_insert BEFORE INSERT ON subconto_values
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.kind_id) NOT IN ('integer', 'null')
   OR typeof(NEW.active) NOT IN ('integer', 'null')
   OR typeof(NEW.currency_id) NOT IN ('integer', 'null')
   OR typeof(NEW.owner_id) NOT IN ('integer', 'null')
   OR typeof(NEW.nonresident) NOT IN ('integer', 'null')
   OR typeof(NEW.parent_id) NOT IN ('integer', 'null')
   OR typeof(NEW.is_group) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'subconto_values: not an integer'); END;

CREATE TRIGGER subconto_values_integers_update BEFORE UPDATE ON subconto_values
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.kind_id IS NOT OLD.kind_id AND typeof(NEW.kind_id) NOT IN ('integer', 'null'))
   OR (NEW.active IS NOT OLD.active AND typeof(NEW.active) NOT IN ('integer', 'null'))
   OR (NEW.currency_id IS NOT OLD.currency_id AND typeof(NEW.currency_id) NOT IN ('integer', 'null'))
   OR (NEW.owner_id IS NOT OLD.owner_id AND typeof(NEW.owner_id) NOT IN ('integer', 'null'))
   OR (NEW.nonresident IS NOT OLD.nonresident AND typeof(NEW.nonresident) NOT IN ('integer', 'null'))
   OR (NEW.parent_id IS NOT OLD.parent_id AND typeof(NEW.parent_id) NOT IN ('integer', 'null'))
   OR (NEW.is_group IS NOT OLD.is_group AND typeof(NEW.is_group) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'subconto_values: not an integer'); END;

CREATE TRIGGER tags_integers_insert BEFORE INSERT ON tags
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'tags: not an integer'); END;

CREATE TRIGGER tags_integers_update BEFORE UPDATE ON tags
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'tags: not an integer'); END;

CREATE TRIGGER warehouses_integers_insert BEFORE INSERT ON warehouses
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.subconto_value_id) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'warehouses: not an integer'); END;

CREATE TRIGGER warehouses_integers_update BEFORE UPDATE ON warehouses
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.subconto_value_id IS NOT OLD.subconto_value_id AND typeof(NEW.subconto_value_id) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'warehouses: not an integer'); END;


-- 2. the closed period -------------------------------------------------------------

CREATE TRIGGER documents_closed_no_insert BEFORE INSERT ON documents
WHEN NEW.status = 'posted' AND NEW.doc_date <= (SELECT closed_through FROM companies WHERE id = NEW.company_id)
BEGIN SELECT RAISE(ABORT, 'period is closed: document not posted'); END;

CREATE TRIGGER documents_closed_no_update BEFORE UPDATE ON documents
WHEN (OLD.status = 'posted' AND OLD.doc_date <= (SELECT closed_through FROM companies WHERE id = OLD.company_id))
  OR (NEW.status = 'posted' AND OLD.status <> 'posted'
      AND NEW.doc_date <= (SELECT closed_through FROM companies WHERE id = NEW.company_id))
BEGIN SELECT RAISE(ABORT, 'period is closed: posted document is unchanged'); END;

CREATE TRIGGER inventory_documents_closed_no_insert BEFORE INSERT ON inventory_documents
WHEN NEW.status = 'posted' AND NEW.doc_date <= (SELECT closed_through FROM companies WHERE id = NEW.company_id)
BEGIN SELECT RAISE(ABORT, 'period is closed: inventory document not posted'); END;

CREATE TRIGGER inventory_documents_closed_no_update BEFORE UPDATE ON inventory_documents
WHEN (OLD.status = 'posted' AND OLD.doc_date <= (SELECT closed_through FROM companies WHERE id = OLD.company_id))
  OR (NEW.status = 'posted' AND OLD.status <> 'posted'
      AND NEW.doc_date <= (SELECT closed_through FROM companies WHERE id = NEW.company_id))
BEGIN SELECT RAISE(ABORT, 'period is closed: posted inventory document is unchanged'); END;


-- 3. what a module builds a closed document from -----------------------------------

CREATE TRIGGER bank_operations_closed_no_insert BEFORE INSERT ON bank_operations
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = NEW.document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: bank_operations unchanged'); END;

CREATE TRIGGER bank_operations_closed_no_update BEFORE UPDATE ON bank_operations
WHEN (NEW.document_id IS NOT OLD.document_id
    OR NEW.direction IS NOT OLD.direction
    OR NEW.kind IS NOT OLD.kind
    OR NEW.account_id IS NOT OLD.account_id
    OR NEW.sc1 IS NOT OLD.sc1
    OR NEW.sc2 IS NOT OLD.sc2
    OR NEW.sc3 IS NOT OLD.sc3
    OR NEW.currency_id IS NOT OLD.currency_id
    OR NEW.counterparty_id IS NOT OLD.counterparty_id)
 AND (EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = OLD.document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = NEW.document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through))
BEGIN SELECT RAISE(ABORT, 'period is closed: bank_operations unchanged'); END;

CREATE TRIGGER bank_operations_closed_no_delete BEFORE DELETE ON bank_operations
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = OLD.document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: bank_operations unchanged'); END;

CREATE TRIGGER bank_operation_lines_closed_no_insert BEFORE INSERT ON bank_operation_lines
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT document_id FROM bank_operations WHERE id = NEW.operation_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: bank_operation_lines unchanged'); END;

CREATE TRIGGER bank_operation_lines_closed_no_update BEFORE UPDATE ON bank_operation_lines
WHEN (NEW.operation_id IS NOT OLD.operation_id
    OR NEW.line_no IS NOT OLD.line_no
    OR NEW.account_id IS NOT OLD.account_id
    OR NEW.sc1 IS NOT OLD.sc1
    OR NEW.sc2 IS NOT OLD.sc2
    OR NEW.sc3 IS NOT OLD.sc3
    OR NEW.amount IS NOT OLD.amount
    OR NEW.invoice IS NOT OLD.invoice
    OR NEW.pays_vat IS NOT OLD.pays_vat)
 AND (EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT document_id FROM bank_operations WHERE id = OLD.operation_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT document_id FROM bank_operations WHERE id = NEW.operation_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through))
BEGIN SELECT RAISE(ABORT, 'period is closed: bank_operation_lines unchanged'); END;

CREATE TRIGGER bank_operation_lines_closed_no_delete BEFORE DELETE ON bank_operation_lines
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT document_id FROM bank_operations WHERE id = OLD.operation_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: bank_operation_lines unchanged'); END;

CREATE TRIGGER currency_conversions_closed_no_insert BEFORE INSERT ON currency_conversions
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = NEW.document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = NEW.credit_document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: currency_conversions unchanged'); END;

CREATE TRIGGER currency_conversions_closed_no_update BEFORE UPDATE ON currency_conversions
WHEN (NEW.document_id IS NOT OLD.document_id
    OR NEW.from_account_id IS NOT OLD.from_account_id
    OR NEW.from_sc1 IS NOT OLD.from_sc1
    OR NEW.from_sc2 IS NOT OLD.from_sc2
    OR NEW.from_sc3 IS NOT OLD.from_sc3
    OR NEW.from_currency_id IS NOT OLD.from_currency_id
    OR NEW.from_amount IS NOT OLD.from_amount
    OR NEW.to_account_id IS NOT OLD.to_account_id
    OR NEW.to_sc1 IS NOT OLD.to_sc1
    OR NEW.to_sc2 IS NOT OLD.to_sc2
    OR NEW.to_sc3 IS NOT OLD.to_sc3
    OR NEW.to_currency_id IS NOT OLD.to_currency_id
    OR NEW.to_amount IS NOT OLD.to_amount
    OR NEW.to_date IS NOT OLD.to_date)
 AND (EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = OLD.document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = OLD.credit_document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = NEW.document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = NEW.credit_document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through))
BEGIN SELECT RAISE(ABORT, 'period is closed: currency_conversions unchanged'); END;

CREATE TRIGGER currency_conversions_closed_no_delete BEFORE DELETE ON currency_conversions
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = OLD.document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = OLD.credit_document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: currency_conversions unchanged'); END;

CREATE TRIGGER conversion_fees_closed_no_insert BEFORE INSERT ON conversion_fees
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT document_id FROM currency_conversions WHERE id = NEW.conversion_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT credit_document_id FROM currency_conversions WHERE id = NEW.conversion_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: conversion_fees unchanged'); END;

CREATE TRIGGER conversion_fees_closed_no_update BEFORE UPDATE ON conversion_fees
WHEN (NEW.conversion_id IS NOT OLD.conversion_id
    OR NEW.line_no IS NOT OLD.line_no
    OR NEW.account_id IS NOT OLD.account_id
    OR NEW.sc1 IS NOT OLD.sc1
    OR NEW.sc2 IS NOT OLD.sc2
    OR NEW.sc3 IS NOT OLD.sc3
    OR NEW.currency_id IS NOT OLD.currency_id
    OR NEW.amount IS NOT OLD.amount
    OR NEW.expense_account_id IS NOT OLD.expense_account_id)
 AND (EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT document_id FROM currency_conversions WHERE id = OLD.conversion_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT credit_document_id FROM currency_conversions WHERE id = OLD.conversion_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT document_id FROM currency_conversions WHERE id = NEW.conversion_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT credit_document_id FROM currency_conversions WHERE id = NEW.conversion_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through))
BEGIN SELECT RAISE(ABORT, 'period is closed: conversion_fees unchanged'); END;

CREATE TRIGGER conversion_fees_closed_no_delete BEFORE DELETE ON conversion_fees
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT document_id FROM currency_conversions WHERE id = OLD.conversion_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = (SELECT credit_document_id FROM currency_conversions WHERE id = OLD.conversion_id) AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: conversion_fees unchanged'); END;

CREATE TRIGGER inventory_accruals_closed_no_insert BEFORE INSERT ON inventory_accruals
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = NEW.gl_document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: inventory_accruals unchanged'); END;

CREATE TRIGGER inventory_accruals_closed_no_update BEFORE UPDATE ON inventory_accruals
WHEN (NEW.document_id IS NOT OLD.document_id
    OR NEW.expense_date IS NOT OLD.expense_date
    OR NEW.gl_document_id IS NOT OLD.gl_document_id)
 AND (EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = OLD.gl_document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
   OR EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = NEW.gl_document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through))
BEGIN SELECT RAISE(ABORT, 'period is closed: inventory_accruals unchanged'); END;

CREATE TRIGGER inventory_accruals_closed_no_delete BEFORE DELETE ON inventory_accruals
WHEN EXISTS (SELECT 1 FROM documents d JOIN companies c ON c.id = d.company_id WHERE d.id = OLD.gl_document_id AND d.status = 'posted' AND d.doc_date <= c.closed_through)
BEGIN SELECT RAISE(ABORT, 'period is closed: inventory_accruals unchanged'); END;
