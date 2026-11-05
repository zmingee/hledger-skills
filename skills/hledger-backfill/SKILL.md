---
name: hledger-backfill
description: Imports transaction history dated before the opening-balance entry of the hledger journal, then moves the opening entry to an earlier date and changes its account lines so all later balances stay the same. Uses the hledger-import skill for each file. Takes the paths of the monthly CSV files as its argument. Use when the user wants to import older months or history that is older than the opening balance. Triggers on phrases like "backfill", "hledger backfill", "import history before the opening balance", "import older months", "backdate the opening balance", "move the opening balance earlier", or "import earlier transactions".
---

# hledger Backfill Skill

The arguments are the paths to the monthly CSV files of the older history. Example:
`/hledger-backfill ~/Downloads/CHECKING_2025-11.csv ~/Downloads/CHECKING_2025-12.csv`

The deliverable is older entries in the journal, a changed opening-balance entry, and a summary.

This skill builds on the `hledger-import` skill. Install that skill first. For each CSV,
follow its procedure (file, convert, dedup, append, post-check). Do not repeat that procedure
here. This skill adds only the opening-balance logic and the checks.

## Hard rules

1. **Never stage, commit, or run any git command.**
2. **Edit only the opening-balance entry** (its date and its amounts). Never edit another
   existing entry.
3. **Make a backup before the first change.** Never overwrite a backup file.
4. **Restore the backup and stop if `hledger check` fails.** Show the error.
5. **Show a failed check or a balance mismatch before the summary.** Do not report success when
   any anchor differs.
6. **Never calculate an opening line by hand.** Use the commands in this skill.
7. **Never invent an account.** Add an opening line only for an account that the new
   transactions touch (Procedure, step 8).
8. **Ask the user before you delete any `_partial` file.**
9. **Never install a package.** If `hledger` is not installed, stop and tell the user.
10. **Never run `hledger-sort-journal`.** This skill does not sort the journal.

The `hledger-import` rule "never edit an existing entry" has one exception here: the opening
entry.

## Paths

The finance directory is the directory that contains the `hledger/` ledger directory. Set
`FINANCE` to its path. Ask the user if you cannot find it. Run every command from that
directory. `J` is `hledger/personal.journal`.

| Item | Path |
|---|---|
| Journal | `hledger/personal.journal` |
| Backup (first) | `/tmp/personal.journal.<YYYYMMDD-HHMMSS>.bak` |
| Backup (before the opening edit) | `/tmp/personal.journal.<YYYYMMDD-HHMMSS>.bak` (new name) |
| Anchors before | `/tmp/hledger-backfill.anchor-before.txt` |
| Anchors after | `/tmp/hledger-backfill.anchor-after.txt` |
| Added entries | `/tmp/hledger-backfill.added.journal` |
| Entries on or after the old opening date, before | `/tmp/hledger-backfill.later-before.txt` |

A backup name must be unique. If the file exists, add a counter suffix, for example
`.bak.1`. Never overwrite a backup.

## Definitions

- **Old opening date** (`OLD`): the date of the entry that has a posting to
  `Equity:Opening Balances`. The line before it is `; ===== Opening balance =====`.
- **Balance-sheet account:** an account that starts with `Assets:` or `Liabilities:`.
- **Anchor:** the balance of one balance-sheet account at a fixed date. It must not change.
- **New opening date** (`NEW`): the day before the oldest new transaction. Example: `2025-12-31`
  when the history starts on `2026-01-01`.

## Procedure

1. **Check the journal.** Run `hledger -f hledger/personal.journal check`. Stop if it fails.
   Find `OLD` and the old opening lines:
   `hledger -f hledger/personal.journal print 'acct:Equity:Opening Balances'`.
   Stop if there is not exactly one such entry.
2. **List the files.** Put the CSV files in date order, oldest first. Find the first and the
   last date of the history.
3. **Look for a gap.** The newest history month must be the month of the day before `OLD`.
   No month can be missing between two files. If a month is missing, ask the user to import
   it first or to confirm. A missing month goes into the opening line as a plug.
4. **Back up.** Copy the journal to a backup path. Tell the user the path.
5. **Save the anchors.** Write these two reports to `/tmp/hledger-backfill.anchor-before.txt`:

   ```text
   echo "== through OLD" > /tmp/hledger-backfill.anchor-before.txt
   hledger -f hledger/personal.journal bal -N --flat -E -e <OLD + 1 day> \
       'acct:^(Assets|Liabilities)' >> /tmp/hledger-backfill.anchor-before.txt
   echo "== end of journal" >> /tmp/hledger-backfill.anchor-before.txt
   hledger -f hledger/personal.journal bal -N --flat -E \
       'acct:^(Assets|Liabilities)' >> /tmp/hledger-backfill.anchor-before.txt
   ```

   The option `-e` excludes its date, so `-e <OLD + 1 day>` includes `OLD`. The option `-E`
   keeps accounts with a zero balance.

   Also save the entries on or after `OLD`, without the opening entry:

   ```text
   hledger -f hledger/personal.journal print date:<OLD>.. \
       not:'acct:Equity:Opening Balances' > /tmp/hledger-backfill.later-before.txt
   ```

   Keep the old opening lines. The command in step 1 shows them.
6. **Import each file.** Use the `hledger-import` procedure for each CSV, oldest first. Do not
   change the opening entry yet. After each append, add the kept entries to the added file:
   `cat /tmp/hledger-import.new.journal >> /tmp/hledger-backfill.added.journal`. Do this
   before the import skill deletes its temporary files. Keep for each file: rows, skipped
   rows, appended entries, and the list of skipped rows.
7. **Calculate net_added.** Run this on the added file, after all files are done:

   ```text
   hledger -f /tmp/hledger-backfill.added.journal bal -N --flat -O csv \
       'acct:^(Assets|Liabilities)'
   ```

   The result is the net change of each balance-sheet account. Include every account that the
   new entries touch, not only the account of the CSV. A transfer posts to two accounts.
   Example: a checking file records a transfer to savings and a payment to the card.
8. **Calculate each new opening line.** The formula is
   `new opening line = old opening line - net_added`, to the cent. Use exact decimals:

   ```text
   python3 -c 'from decimal import Decimal as D; print(D("<old>") - D("<net_added>"))'
   ```

   If an account is in `net_added` but not in the opening entry, add a line for it. Its old
   amount is `0`, so the new line is `0 - net_added`. Leave an opening line unchanged when its
   account has no new entries.
9. **Back up again.** Copy the journal to a new backup path (the imports are now in it).
   Tell the user the path.
10. **Edit the opening entry.** Change its date to `NEW`. Change its amounts to the values from
    step 8. Do not change any other entry. Keep the `Equity:Opening Balances` line without an
    amount.
11. **Check.** Run `hledger -f hledger/personal.journal check`. If it fails, restore the
    backup from step 9, show the error, and stop.
12. **Verify the anchors.** Write the same two reports as in step 5 to
    `/tmp/hledger-backfill.anchor-after.txt`. Use the same `OLD`. Then run
    `diff /tmp/hledger-backfill.anchor-before.txt /tmp/hledger-backfill.anchor-after.txt`.
    Any difference means a missing or wrong adjustment. Show the difference before the
    summary. Do not report success.
13. **Verify the later entries.** Run the `print` command from step 5 again. Write the result
    to `/tmp/hledger-backfill.later-after.txt`. Run `diff` against
    `/tmp/hledger-backfill.later-before.txt`. There must be no difference.
14. **Check the transfer pairs** (below).
15. **Check the card payments** (below).
16. **Summarize** (below).
17. **Tell the user** to run the `hledger-sort-journal` skill. Tell the user to compare the new
    opening lines with the account statements.
18. Delete the files `/tmp/hledger-backfill.*`. Keep the backups.

## Transfer pairs

The sending account records a transfer. The receiving file skips it with its rules.

For each file, list every skipped row. Tell the user which other file completes the pair.
Example: the savings file skips a deposit from checking, so the checking file must be imported.

If one side of a pair is imported and the other side is not, the opening line is provisional.
Example: the checking opening line is too high when the savings-to-checking transfers are
missing. Mark the opening "provisional" in the summary until the files of all accounts for the
period are imported.

## Card payments

The card rules skip each payment row. The checking file
must record one payment for each skipped row. It must have the same amount and a date within
about 5 days.

List the checking payments to the card:

```text
hledger -f /tmp/hledger-backfill.added.journal reg 'acct:^<card account>$'
```

Match each skipped card row to one payment. List every skipped row that has no match. If the
checking file is not imported yet, say so.

## Summary

Use plain text. Example:

```text
Backfill: 2025-11 and 2025-12, 2 files per account
Files:
  example-bank_checking_2025-11.csv  rows 58  skipped 2  appended 56
  example-bank_checking_2025-12.csv  rows 61  skipped 1  appended 60
Net change per touched account:
  Assets:Bank:Example:Checking     -1,200.00
  Assets:Bank:Example:Savings          +500.00
  Liabilities:CC:Example:Card          -300.00
Opening entry: 2025-12-31 -> 2025-10-31
  Assets:Bank:Example:Checking   10,000.00 -> 11,200.00
  Assets:Bank:Example:Savings     5,000.00 -> 4,500.00
  Liabilities:CC:Example:Card         -50.00 -> 250.00
Anchors: all equal at OLD and at the end of the journal - OK
Later entries unchanged: OK
journal check: OK
Skipped transfer rows: 3 (other file needed: example savings 2025-11)
Unmatched card payments: 0
Opening status: provisional (savings file is not imported)
Backups: /tmp/personal.journal.<YYYYMMDD-HHMMSS>.bak, /tmp/personal.journal.<YYYYMMDD-HHMMSS>.bak
Next: run hledger-sort-journal. Compare the new opening lines with your statements.
```

The status is "complete" only when the files of all accounts for the period are imported and
all transfer pairs and card payments match.

## Failure behavior

| Condition | Action |
|---|---|
| `hledger check` fails before the start | Stop. Show the error. |
| No opening entry, or more than one | Stop. Ask the user. |
| A month is missing | Ask the user to import it or to confirm. |
| An import step fails | Follow the `hledger-import` failure rules. Do not edit the opening entry. |
| `hledger check` fails after the opening edit | Restore the backup from step 9. Show the error. Stop. |
| An anchor differs | Show the difference first. Do not report success. |
| A later entry changed | Show the difference first. Restore the backup from step 9. |
| `hledger` not installed | Stop. Do not install it. |

## Out of scope

- Sorting the journal. Use the `hledger-sort-journal` skill.
- Filing, conversion, dedup, and payee rules. The `hledger-import` skill does these.
- Statement PDFs, paystubs, and the old `homebank/` and `ledger-cli/` data.
- Changing any entry other than the opening entry.
