-- A line of a bank operation says what it pays when one payment pays several things: the
-- customs' duty, excise and fees are three lines on the same account (D221). Empty — the
-- operation's own text, as before.
ALTER TABLE bank_operation_lines ADD COLUMN memo TEXT NOT NULL DEFAULT '';
