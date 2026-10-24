-- Indexes under the reads the schema had none for (docs/ENGINEERING.md, 3.3; session 49).
--
-- The journal lists a company's documents of a period in date order whatever their status
-- (queries.list_documents); the index of 0001 starts with the status, so this read every
-- document of the company and sorted them in a temporary tree.
CREATE INDEX documents_by_date ON documents (company_id, doc_date, number);

-- A contract belongs to a counterparty (owner_id, 0009): deleting or checking the
-- counterparty read every value of the company to find its contracts.
CREATE INDEX subconto_values_owner ON subconto_values (company_id, owner_id);

-- The file declares itself a Modern GL company file ('MGL1', infrastructure.db
-- APPLICATION_ID): a file of another program is refused before its tables are read.
PRAGMA application_id = 1296518193;
