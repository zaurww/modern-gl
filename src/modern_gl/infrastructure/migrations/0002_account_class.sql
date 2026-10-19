-- Account class (level 1 of financial statement classification) and contra flag.
-- NULL class = not classified yet; the user can set it in the chart of accounts.

ALTER TABLE accounts ADD COLUMN account_class TEXT
    CHECK (account_class IN ('asset', 'liability', 'equity', 'revenue', 'expense'));
ALTER TABLE accounts ADD COLUMN contra INTEGER NOT NULL DEFAULT 0;

-- Companies created from the 1C 7.7 template before this migration: classify by code,
-- exactly as the template does now. Accounts with other codes stay unclassified.
UPDATE accounts SET account_class = 'asset' WHERE code IN (
    '01', '02', '03', '04', '05', '07', '08', '09', '10', '10.1', '10.3', '10.5', '10.9',
    '14', '15', '16', '19', '19.1', '19.3', '19.4', '20', '21', '23', '29', '41', '41.1',
    '41.2', '42', '43', '45', '46', '50', '51', '52', '55', '57', '58', '59', '60.2', '62',
    '62.1', '63', '71', '73', '75.1', '76.2', '76.3', '94', '97');
UPDATE accounts SET account_class = 'liability' WHERE code IN (
    '60', '60.1', '62.2', '66', '67', '68', '68.1', '68.2', '68.4', '68.8', '69', '70', '75',
    '75.2', '76', '76.1', '76.4', '76.5', '77', '79', '86', '96', '98');
UPDATE accounts SET account_class = 'equity' WHERE code IN (
    '80', '81', '82', '83', '84', '90.9', '91.9', '99');
UPDATE accounts SET account_class = 'revenue' WHERE code IN ('90', '90.1', '90.3', '91', '91.1');
UPDATE accounts SET account_class = 'expense' WHERE code IN (
    '25', '26', '28', '40', '44', '90.2', '91.2');
UPDATE accounts SET contra = 1 WHERE code IN (
    '02', '05', '14', '42', '59', '63', '81', '90.3');
