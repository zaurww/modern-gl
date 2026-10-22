-- Advances on their own account (D78): a payment beyond what is owed goes to the account
-- of the role advance_paid / advance_received. A company whose chart has exactly one
-- active account of such a type (61 / 64 of the classic chart, 60.2 / 62.2 of 1C 7.7)
-- gets it as the role; the bank's settings can change it or clear it.

INSERT INTO account_roles (company_id, role, account_id)
SELECT a.company_id, a.account_type, MIN(a.id)
FROM accounts a
WHERE a.account_type IN ('advance_paid', 'advance_received')
  AND a.is_group = 0 AND a.active = 1
  AND NOT EXISTS (
      SELECT 1 FROM account_roles r
      WHERE r.company_id = a.company_id AND r.role = a.account_type
  )
GROUP BY a.company_id, a.account_type
HAVING COUNT(*) = 1;
