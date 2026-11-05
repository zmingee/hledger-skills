---
name: hledger-sort-journal
description: Sorts the hledger journal by month, then source account, then date, and writes comment section headers. It only reorders entries and never edits entry text. It checks the result and restores a backup if a check fails. Takes an optional journal path as its argument. Use when the user wants to sort or organize the hledger journal or personal.journal. Triggers on phrases like "sort the journal", "organize the journal", "sort hledger", or "regroup journal by month".
---

# hledger Sort Journal Skill

The argument is an optional path to a journal. The default is `hledger/personal.journal`.
Example: `/hledger-sort-journal`

The deliverable is a sorted journal and a short summary. The skill only reorders entries.

## Hard rules

1. **Never stage, commit, or run any git command.** Do not run git in the finance directory.
2. **Never edit the text of an entry.** Only change the order of entries and the header lines.
3. **Never install a package.** If `hledger` is not installed, stop and tell the user.
4. **Never delete a backup.** The script writes each backup to a new file.
5. **Show a failed check before the summary,** not inside it.
6. **Use the script for the sort.** Do not sort by hand.

## Paths

The finance directory is the directory that contains the `hledger/` ledger directory. Set
`FINANCE` to its path. Ask the user if you cannot find it. Run every command from that
directory. The default journal path is relative to the finance directory.

| Item | Path |
|---|---|
| Journal (default) | `hledger/personal.journal` |
| Sort script | `scripts/sort_journal.py` in this skill's directory |
| Backup | `/tmp/<journal name>.<YYYYMMDD-HHMMSS>.bak` |

## Layout that the script writes

1. The periodic blocks (lines that start with `~`) stay first. They do not change.
2. The header `; ===== Opening balance =====` and the opening-balance entry.
3. For each month, in ascending order: the header `; ===== YYYY-MM =====`.
4. For each source account in that month, in ascending order: the header
   `; ----- YYYY-MM: <account> -----`. Then the entries of that account, by date.

Entries with the same date keep their original order. One blank line separates blocks. The
file ends with one newline.

The script removes the generated header lines from an earlier run. A standalone comment
line that is not a generated header stops the sort (see the failure table).

## Source account

The source account is the account that sends the money.

1. Take the postings on `Assets:` and `Liabilities:` accounts.
2. The source is the first of these postings with a negative amount.
3. If no posting is negative, the source is the first of these postings.
4. If there is no such posting, the source is the first posting.

A transfer is under the sending account. A deposit is under the receiving account. A card
purchase is under the card.

## Procedure

Let `JOURNAL` be the argument, or the default path. Let `SCRIPT` be the sort
script path (Paths).

1. **Preview.** Run:
   `python3 SCRIPT --journal JOURNAL --dry-run`
2. **Sort.** Run the same command without `--dry-run`. The script does these steps:
   1. It runs `hledger check`. It stops if the check fails.
   2. It copies the journal to a backup file.
   3. It removes the old header lines, sorts the entries, and writes the journal.
   4. It verifies the result (see Verification).
3. **Report.** Show any error first. Then show the summary.

The script is safe to run again. A second run on a sorted journal gives the same file.

## Verification

The script restores the backup and exits with an error if one of these checks fails:

- `hledger check` fails on the new journal.
- The output of `hledger bal -N` is different from the output before the sort.
- The set of entries is different from the set before the sort.
- The text of an entry is different from the text before the sort.

## Summary

Use plain text. Example:

```text
Sorted: 120 transactions, 105 moved. Checks passed. Backup: /tmp/personal.journal.<YYYYMMDD-HHMMSS>.bak
```

Tell the user the backup path.

## Failure behavior

| Condition | Action |
|---|---|
| `hledger` not installed | Stop. Do not install it. |
| Journal not found | Stop. Ask the user for the path. |
| `hledger check` fails before the sort | Stop. Show the error. The journal does not change. |
| A block does not start with a date or `~` | Stop. Show the block. The journal does not change. |
| A standalone comment line other than a generated header | Stop. Show the line. The journal does not change. |
| A verification check fails | The script restores the backup. Show the error first. |

## Out of scope

- Editing, merging, or deleting entries.
- Included journal files. The script sorts one file.
- Rules files and CSV files.
- Sorting by anything other than month, source account, and date.
