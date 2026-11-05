---
name: hledger-categorize
description: Summarizes the journal entries that post to the bare account Expenses (uncategorized). After the user approves categories, it changes those existing entries in bulk and adds the same rules to payees.rules for future imports. Use when the user wants to categorize uncategorized entries. Triggers on phrases like "categorize the uncategorized", "bulk categorize", "what is left uncategorized", "categorize these merchants", or "summarize uncategorized rows".
---

# hledger Categorize Skill

The skill finds entries that post to the bare account `Expenses`. The user states the categories. The skill then edits those entries and records the rules in `hledger/rules/payees.rules`.

This skill is separate from `hledger-import`. The import skill does not edit old entries. This skill edits existing entries of any age.

## Hard rules

1. **Never stage, commit, or run any git command.** Do not run git in the finance directory.
2. **Change only entries whose posting is exactly the bare account `Expenses`.** Never touch an entry that has a categorized account.
3. **Never change an amount, a date, a status, a raw comment, or a bank-account posting.**
4. **Make a backup before each write.** The script does this.
5. **Restore the backup if `hledger check` fails or an asset or liability balance changes.** The script does this.
6. **Never invent an account or a payee name.** Use the names that the user gives. If the user gave none, ask.
7. **Never install a package.** If `hledger` is not installed, stop and tell the user.
8. **Show a failure before the summary,** not inside it.

## Paths

The finance directory is the directory that contains the `hledger/` ledger directory. Set
`FINANCE` to its path. Ask the user if you cannot find it. Run every command from that
directory.

| Item | Path |
|---|---|
| Journal | `hledger/personal.journal` |
| Shared payee rules | `hledger/rules/payees.rules` |
| Script | `scripts/categorize.py` in this skill's directory |
| Spec file | `/tmp/hledger-categorize.spec.tsv` |
| Converted file | `/tmp/hledger-categorize.conv.journal` |
| Backup | `/tmp/<journal name>.<YYYYMMDD-HHMMSS>.bak` |

The script never overwrites a backup. It adds a counter to the name when the file exists.

## Spec file

The spec file has one rule on each line. A tab separates the fields:

```text
REGEX<TAB>PAYEE<TAB>ACCOUNT[<TAB>POSTING_COMMENT]
```

- Lines that start with `#` and blank lines are ignored.
- The script matches REGEX against the raw bank text of the entry. The match ignores case.
- The raw bank text is the text after `; ` on the header line. Without a comment, it is the description.
- PAYEE `-` keeps the existing payee.
- POSTING_COMMENT is optional. The script adds it to the changed posting as `  ; POSTING_COMMENT`.
- The first rule that matches an entry wins.

Example (each gap is one tab):

```text
WAL-MART	Walmart	Expenses:Shopping:Walmart
UNITED DAIR	United Dairy Farmers	Expenses:Food:Groceries	milk run
```

## Procedure

Let `SCRIPT` be the script path.

1. **List.** Run `python3 SCRIPT --journal hledger/personal.journal --list`. Show the summary to the user. Add `--top N` to see more groups.
2. **Get categories.** The user states the category for each merchant group.
   - Use the accounts that the user names, as given.
   - Run `hledger -f hledger/personal.journal accounts`. Also read the `~` periodic block at the top of the journal.
   - If an account is in neither place, call it **new**. List each new account in the summary.
   - If the user names no account for a group, ask. An existing account can be a suggestion in a question only. Example: an IRS levy has no account. Ask whether `Expenses:Taxes:Federal` is correct.
   - If the user names no payee, ask. Do not make one up.
3. **Write the spec.** Write the rules to `/tmp/hledger-categorize.spec.tsv`. Then run a dry run:
   `python3 SCRIPT --journal hledger/personal.journal --apply /tmp/hledger-categorize.spec.tsv --dry-run`
   Show the match count of each rule and the total. Show the rules with zero matches. Show the skipped entries.
4. **Apply.** Ask the user to confirm the counts. Then run:
   `python3 SCRIPT --journal hledger/personal.journal --apply /tmp/hledger-categorize.spec.tsv --payees-rules hledger/rules/payees.rules`
   The script backs up the journal, writes it, and runs `hledger check`. It also compares `hledger bal Assets Liabilities -N` before and after. On a failure it restores the backup and exits with a non-zero code.
5. **Verify.** Convert each filed CSV with its rules file. Put all output in one file:
   `hledger print -f CSV --rules-file hledger/rules/RULES >> /tmp/hledger-categorize.conv.journal`
   The registry in the `hledger-import` skill names the rules file for each CSV. Then run:
   `python3 SCRIPT --journal hledger/personal.journal --verify-against /tmp/hledger-categorize.conv.journal --spec /tmp/hledger-categorize.spec.tsv`
   The result `Only in rules: 0   Only in journal: 0` is good. Show any other result to the user.
6. **Re-list.** Run `--list` again. Report the remaining count and total. Show the next largest groups.
7. **Clean up.** Delete `/tmp/hledger-categorize.spec.tsv` and `/tmp/hledger-categorize.conv.journal`. Keep the backup. Tell the user the backup path.

## One-off items

Some entries need no rule. Examples: checks, levies, and large one-time payments.

- Do not write a payee rule for them.
- Use a spec line with PAYEE `-` and a POSTING_COMMENT. The script then edits the entry and writes no rule block.
- Use a regex that matches only that entry, for example the check number.

## What the script does

**List mode.** The script counts the entries with a bare `Expenses` posting and adds their amounts. It shows the count for each month. It groups the entries by merchant key and sorts the groups by absolute total. It does not guess categories.

The merchant key is the raw bank text without these prefixes: `POS DEBIT - RECURRING`, `POS DEBIT`, `AUTOMATIC DEBIT`, `DIRECT DEPOSIT`. The script cuts the text at the first space run that is followed by a digit. The key has at most 24 characters.

A separate list shows the entries that need input. These are entries over 1000, check payments, and entries with a negative amount on the `Expenses` posting. They are not in the merchant groups.

**Apply mode.** The script changes an entry only when exactly one posting has the account `Expenses`. The script skips and reports an entry with two or more bare postings. The script changes only text in that entry:

- The account `Expenses` becomes ACCOUNT. The amount column stays in place when the gap is wide enough.
- The payee on the header line changes. The date, the status, and the raw comment stay. If the header has no comment, the script adds the old description as the raw comment.
- POSTING_COMMENT is added to the posting line.

A second run with the same spec changes nothing. When a rule has no entry to
change (no match, all its entries are already categorized, or they are
skipped), the script stops with exit code 2.

**Payees rules.** With `--payees-rules`, the script adds one block for each new rule after the line `# --- Added <YYYY-MM> (user-approved categories) ---`:

```text
if %rawdesc <PATTERN>
    description <PAYEE>
    account1 <ACCOUNT>
```

- A rule with PAYEE `-` and a comment is a one-off. It has no block.
- A rule with PAYEE `-` and no comment has an account-only block (no `description` line).
- The script never edits an existing block. If the file already has the same `if %rawdesc <PATTERN>` line, the script skips the rule and reports it.
- The script writes the rules file only after the journal passes the checks. A dry run writes nothing.

**Verify mode.** The script reads the entries of the journal and of the converted file that match a spec regex. For the journal, it uses only the dates in the range of the converted file. It compares the payee, the status, the accounts, and the amounts. It ignores comments and extra spaces.

## Failure behavior

| Condition | Action |
|---|---|
| `hledger check` fails before the change | Stop. Show the error. The journal is not changed. |
| The rules file does not exist | The script stops with exit code 2. Show the error. Nothing changes. |
| `hledger check` fails after the change | The script restores the backup. Show the error. |
| Writing the journal fails (for example, permissions) | The script restores the backup. Show the error. |
| Asset or liability balances change | The script restores the backup. Show the warning. |
| Spec line has a bad format or a bad regex | The script stops with exit code 2. Show the line. Ask the user. |
| A rule has no entry to change (no match, already categorized, or skipped) | The script stops with exit code 2. Show the rule. Ask the user if the regex is correct. Nothing changes. |
| Entry with 2 or more bare postings | The script skips it. Tell the user to edit it by hand. |
| `--verify-against` shows a difference | Show the entries. Ask the user. |
| `hledger` not installed | Stop. Do not install it. |

## Out of scope

- Import of CSV files. Use the `hledger-import` skill.
- Entries that already have a categorized account.
- A split of one payment into several postings.
- Changes to the amount, the date, or the status of an entry.
- The old `homebank/` and `ledger-cli/` data.
