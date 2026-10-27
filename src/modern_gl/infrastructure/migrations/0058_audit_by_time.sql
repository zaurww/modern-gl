-- «Журнал действий»: the events of a company by time, newest first.
CREATE INDEX audit_by_company_time ON audit_events (company_id, at);
