---
name: hledger-import
description: Files a downloaded bank or credit card transaction CSV, imports it into the hledger journal with pending status, skips transactions that already exist, checks the result, and reports a summary. Then proposes new payee rules. Takes the path to the CSV file as its argument. Use when the user wants to import transactions into hledger or personal.journal. Triggers on phrases like "hledger import", "import transactions", "import this CSV", "import my bank file", "file this statement", "add these transactions to the journal", "import checking", or "import savings".
---

# hledger Import Skill

The argument is the path to one downloaded transaction CSV. Example:
`/hledger-import ~/Downloads/CHECKING_Transactions_2026-10-01_2026-10-31.csv`

The deliverable is new entries in the journal and a summary. Do one file for each call.

## Hard rules

1. **Never stage, commit, or run any git command.** Do not run git in the finance directory.
2. **Never edit an existing journal entry.** Only append new entries to the end of the journal.
3. **Never use `hledger import`.** It does not compare the CSV with the journal. Use the dedup
   step in this skill.
4. **Never overwrite a file.** If the target path exists, stop and ask. Never overwrite a backup.
5. **Never install a package.** If `hledger` is not installed, stop and tell the user.
6. **Never invent a payee or an account.** Use only the names that the journal already has.
7. **Show a failed check or a balance mismatch before the summary,** not inside it.
8. **Each appended entry has the `!` status.** Each entry keeps the raw bank text as a comment.
   The rules files produce this. If the converted output does not have it, stop and tell the
   user.

## Paths

The finance directory is the directory that contains the `hledger/` ledger directory. Set
`FINANCE` to its path. Ask the user if you cannot find it. Run every command from that
directory.

| Item | Path |
|---|---|
| Journal | `hledger/personal.journal` |
| Rules | `hledger/rules/<name>.rules` |
| Shared payee rules | `hledger/rules/payees.rules` |
| Filed CSV | `<YEAR>/transactions/<institution>_<account-type>_<YYYY-MM>[_partial].csv` |
| Dedup script | `scripts/dedup.py` in this skill's directory |
| Backup | `/tmp/personal.journal.<YYYYMMDD-HHMMSS>.<random>.bak` (from `mktemp`) |

## Registry

The registry maps each file type to its rules file, its bank account, and its CSV header.
The table below is an example. Replace it with your own institutions, accounts, and rules
files before the first import.

| Institution slug | Account type | Rules file | Account | Header line |
|---|---|---|---|---|
| `example-bank` | `checking` | `Example-Checking.rules` | `Assets:Bank:Example:Checking` | `"Account Name","Processed Date","Description",...` |
| `example-card` | `card` | `Example-Card.rules` | `Liabilities:CC:Example:Card` | `Transaction Date,Posted Date,Card No.,Description,...` |
| `example-bank` | `savings` | `Example-Savings.rules` | `Assets:Bank:Example:Savings` | `Account Number,Transaction Description,...` |

The rules files live in `hledger/rules/`. Each one includes `hledger/rules/payees.rules`.

Detect the file type by the first line (the header) first. Then check the file name. If both
fail, or they disagree, ask the user. Do not import. If the rules file for the type does not
exist, stop and show the header.

## Journal format that the rules produce

```text
2026-10-06 ! Kroger  ; POS DEBIT KROGER  500  800-555-0100 OH
    Expenses:Food:Groceries           42.50
    Assets:Bank:Example:Checking
```

- The date is followed by `!` and the **payee**. The user chooses the payee name.
- The comment is the raw bank text, unchanged.
- When no payee rule matches, the raw text is the description, and it is also the comment.
- The bank account posting has no amount. The other side is the bare account `Expenses` when
  no rule matches.
- A transfer has the payee `(XFER) <Institution>`. The other posting is the receiving account.
- Income goes to `Income:<Employer>`.

## Filing

The target path is
`<YEAR>/transactions/<institution>_<account-type>_<YYYY-MM>[_partial].csv`.

1. Read the CSV. Find the minimum and maximum date. For the card, use the posted date.
2. Take `<YEAR>` and `<YYYY-MM>` from the maximum date. If the minimum and maximum dates are in
   different months, ask the user.
3. Add `_partial` when the month is not complete. This is true when the maximum date is in the
   current month and today (`date +%F`) is not after the last day of that month. It is also true
   when the user says so. A file for a finished month has no suffix.
4. If the target exists, stop and ask. Never overwrite it.
5. Make `<YEAR>/transactions/` if it is missing. Then `mv` the file to the target path. This
   removes it from the source location. Use the filed path for all later steps.
6. **Numbered downloads.** The bank can name several downloads the same, such as
   `file.csv`, `file(1).csv`, and `file(2).csv`. Do not trust the order of the names. Read the
   dates in each file and map each file to its month. Show the user the mapping before you file.
7. **Multi-month file.** If one file has more than one month, split it by month. Use the same
   date field as step 1. Keep the header line and the row order in each part. Show the row count
   for each part, and check that the parts add up to the rows of the original file. File each
   part as in this section. Then remove the original. Import each month with its own call
   of the procedure.
8. A full-month file replaces a `_partial` file of the same month. Ask the user before you
   delete the old partial file. The dedup step makes the overlap safe.

## Procedure

Let `CSV` be the filed path, `RULES` the rules file, and `ACCOUNT` the bank account.

1. **Identify** the institution and account type (Registry).
2. **File** the CSV (Filing).
3. **Pre-check.** Run `hledger -f hledger/personal.journal check`. Stop if it fails.
4. **Back up.** Make a unique name, so that two runs in the same second never share a backup:
   `B=$(mktemp /tmp/personal.journal.$(date +%Y%m%d-%H%M%S).XXXXXX --suffix=.bak)`. Then
   `cp hledger/personal.journal "$B"`. Tell the user the path.
5. **Convert.** Run both commands:
   - `hledger print -f CSV --rules-file hledger/rules/RULES > /tmp/hledger-import.cand.journal`
   - `hledger print -f CSV --rules-file hledger/rules/RULES -O csv > /tmp/hledger-import.cand.csv`

   Transaction number N in the journal text is the group of rows with `txnidx` N in the CSV.
6. **Dedup.** Run the dedup step (below).
7. **Append.** Copy only the kept transactions to the end of `hledger/personal.journal`. Keep
   the `hledger print` format. Put one blank line before the first appended entry. Then save
   the checksum: `sha256sum hledger/personal.journal`.
8. **Post-check.**
   - Run `hledger -f hledger/personal.journal check`. If it fails, restore the backup, show the
     error, and stop.
   - Find the sum of the appended amounts on `ACCOUNT`. It must equal the sum of the kept CSV
     rows. Report a mismatch.
   - If the CSV has a running balance (savings), compare it with the journal balance at the
     last date: `hledger -f hledger/personal.journal bal ACCOUNT -e <last date + 1 day>`.
     Report a mismatch.
9. **Summarize** (below). Then **propose rules** (below).
10. Delete the files `/tmp/hledger-import.*` when you finish. Keep the backup.

## Dedup

Let `SCRIPT` be the dedup script path (Paths). Run:

```text
hledger -f hledger/personal.journal print 'acct:^ACCOUNT$' -O csv > /tmp/hledger-import.jrn.csv
python3 SCRIPT \
    --candidate /tmp/hledger-import.cand.csv \
    --journal /tmp/hledger-import.jrn.csv \
    --account ACCOUNT --indexes
```

The script prints JSON with these keys:

| Key | Meaning |
|---|---|
| `keep` | Candidates that are not in the journal. Append these. |
| `skip` | Candidates that already have a journal match. Do not append these. |
| `near_misses` | Kept candidates that have an unmatched journal entry with the same amount and text, and a date within 3 days or in the same month. |
| `keep_indexes` | The `txnidx` values of the kept candidates. |

The script matches on the date, the amount of the bank account posting, and the raw text (the
comment, or the description when there is no comment), with runs of spaces collapsed. It counts
matches: each journal entry matches one candidate only. It does not compare the other
postings, so the categories that the user chose in the journal stay. A hand-split entry matches
on the bank posting amount.

Extract the kept transactions from the candidate journal text. `KEEP` is `keep_indexes` joined
with commas, for example `4,5,6`:

```text
awk -v keep="KEEP" 'BEGIN{RS="";ORS="\n\n";n=split(keep,a,",");for(i=1;i<=n;i++)k[a[i]]=1} k[NR]' \
    /tmp/hledger-import.cand.journal > /tmp/hledger-import.new.journal
```

Append `/tmp/hledger-import.new.journal` to the journal in step 7.

If `keep` is empty, report "nothing new", keep the filed CSV, and stop. Do not change the
journal.

Near misses are not skipped. Show each one to the user, and let the user decide. A near miss
has the same amount and text as a kept candidate. Its date is within 3 days, or in the same
month. A hand-entered entry with a wrong date is a typical near miss. The user can fix it:
the skill does not edit the old entry.

## Transfers

The account that sends the money is the source of truth.

- The sending file records the transfer. The payee is `(XFER) <Institution>`. The other
  posting is the receiving account.
- The receiving file skips the matching inbound row. The rules file does this with `skip`.
- Examples: checking pays the card, so checking records it and the card rules skip the
  payment row. Savings pays checking, so savings records it and checking skips the
  deposit row.

Check the direction of each skip rule. A skip rule must match only the inbound side of the
transfer. Match the direction field (`Credit` or `Debit`) as well as the text. Example: a rule
that skips every transfer row also skips the outbound debits that checking must
record. Then those transfers are missing from the journal. For each transfer type, make sure
that exactly one file records each transfer and the other file skips it.

List every row that the rules skipped in the summary. The user can then see that the sending
file must be imported too. Until that file is imported, the transfer is missing from the
journal.

To count skipped rows, compare the number of data rows in the CSV with the number of
transactions in `/tmp/hledger-import.cand.journal`.

## Balance checks

Use these checks when the CSV or the bank site gives a balance. Show a mismatch before the
summary.

1. **Month end.** If the CSV has a running balance, compare it with the journal balance at each
   month end. Use `hledger -f hledger/personal.journal bal ACCOUNT -e <first day of next month>`.
   Two accounts can post one transfer on different dates. A difference that is the amount of one
   transfer, and that is gone at the next month end, is a timing difference. Report it as such.
2. **Final balance.** After the last import, ask the user to compare the journal balance with
   the balance in the bank web site. For a credit card, a small balance is usual: it is the
   charges that the last payment did not cover.
3. **Opening balance.** The balance at the date of the opening entry must stay the same
   unless the user asks for a backfill (see the `hledger-backfill` skill).

## Summary

Use plain text. Take the counts and totals from `hledger print -O csv` on
`/tmp/hledger-import.new.journal`, not from the CSV. Example:

```text
Imported: example-bank_checking_2026-10-01_2026-10-23.csv
Filed to: 2026/transactions/example-bank_checking_2026-10_partial.csv
Rows in file: 60   Skipped by rules: 0   Already in journal: 41   Appended: 19
Near misses (not skipped): 1
Date range of new rows: 2026-10-20 to 2026-10-23
Payee matched: 14 of 19    Categorized: 12 of 19 (63%)
Uncategorized (bare Expenses): 7
Debits:  total 1,200.00  (15 txns)
Credits: total 2,000.00  (4 txns)
Net change to Assets:Bank:Example:Checking: +800.00
Balance check: journal 3,000.00 vs file 3,000.00 - OK
journal check: OK
Backup: /tmp/personal.journal.<YYYYMMDD-HHMMSS>.bak
```

Definitions:

- **Debits and credits** are cash flow out of and into the bank account. For a credit card, a
  purchase is a debit. Label them in the output.
- **Categorized:** the non-bank posting is not the bare account `Expenses`.
- **Payee matched:** the description is not the raw text.
- Also list the rows that the rules skipped as transfers (see Transfers).

## Proposed rules

After the summary, list the appended transactions that have no payee match or no category. For
each group, propose an `if` block. Propose only a payee and an account that already exist in
the journal.

1. **Group** the rows by a merchant key. Remove the prefixes `POS DEBIT`,
   `POS DEBIT - RECURRING`, `AUTOMATIC DEBIT`, and `DIRECT DEPOSIT`. Remove the trailing store
   number, city, and state.
2. **Find the payee.** Look in the journal for the closest payee. Match the merchant key,
   without regard to case, against the payees and the raw comments. Example:
   `GOOGLE *G1SK002M` matches the payee `Google`.
3. **Find the account.** Use the non-bank account that the journal uses most often for that
   payee.
4. **Show a table:** key, matched payee, proposed account, number of rows, and the `if` block
   text. Example block:

   ```text
   if POS DEBIT KROGER
       description Kroger
       account1 Expenses:Food:Groceries
   ```

   A payee rule sets only the `description` and the account of the other side. Use the field
   names that `hledger/rules/payees.rules` and the institution rules file already use for that
   account. Do not set the bank account.
5. **Ask for approval** of each block. The user can answer all, none, or a list.
6. **Write** the approved blocks to the end of `hledger/rules/payees.rules`.
7. **Re-apply the rules to this run's entries only.** Before you restore, run
   `sha256sum hledger/personal.journal` and compare it with the checksum from step 7. If the
   checksums differ, the journal changed after the append. Stop and ask the user. If they are
   equal:
   1. Restore the backup over `hledger/personal.journal`.
   2. Run steps 5 to 8 again. Do not make a new backup. The dedup step skips the entries that
      were in the journal before the first run, so the skill appends only its own entries.
   3. Report the new counts.
8. **No match** in the journal: list the group as "unknown". Do not invent a payee or an
   account. Ask the user.

### Ambiguous payees

Use `Expenses:General` as the account when:

- the payee has more than one account in the journal, or
- the account is a poor fit. Example: Amazon is `Expenses:Medical` in the history, but Amazon
  sells anything.

Mark these rows "default General" in the table. The user splits the entry by hand later. The
skill does not split a payment into several expense postings.

## Failure behavior

| Condition | Action |
|---|---|
| Unknown header, or no rules file | Stop. Show the header. Ask the user. |
| Target file exists | Stop. Ask. |
| All rows already in journal | Report "nothing new". Keep the filed CSV. Stop. |
| `hledger check` fails after append | Restore the backup. Show the error. |
| Balance mismatch | Keep the import. Show the warning first. |
| `hledger` not installed | Stop. Do not install it. |

## Out of scope

- A batch of files. Call the skill once for each file.
- Statement PDFs, paystubs, and the old `homebank/` and `ledger-cli/` data.
- An automatic split of one payment into several expense postings.
