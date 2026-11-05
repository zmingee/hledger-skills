#!/usr/bin/env python3
"""Summarize and bulk-categorize journal entries that post to bare "Expenses".

Modes (one or more can be given in one call):

  --list                  Summarize the entries that have a posting with the
                          account "Expenses" (exactly). Does not guess.
  --apply SPEC.tsv        Change the bare "Expenses" account and the payee of
                          matching entries. SPEC lines are tab-separated:
                          REGEX, PAYEE, ACCOUNT [, POSTING_COMMENT].
                          PAYEE "-" keeps the old payee. Use --dry-run to
                          only count. Without --dry-run the script backs up
                          the journal, writes, checks the result, and restores
                          the backup if the check fails.
  --payees-rules PATH     With --apply: append one "if %rawdesc" block for
                          each new rule to this rules file.
  --verify-against FILE   Compare the matching entries of the journal with the
                          transactions in FILE (hledger print output made with
                          the rules files). Takes the regexes from --spec or
                          from --apply.

The script edits text inside the matching entries only. It never runs git.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

BARE_ACCOUNT = "Expenses"
BACKUP_DIR = "/tmp"
KEY_PREFIXES = [
    "POS DEBIT - RECURRING",
    "POS DEBIT",
    "AUTOMATIC DEBIT",
    "DIRECT DEPOSIT",
]
KEY_MAX = 24
LARGE_AMOUNT = Decimal(1000)
CHECK_RE = re.compile(r"^CHECK\s+\d+", re.IGNORECASE)

DATE = r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
HEADER_RE = re.compile(
    r"^(?P<date>" + DATE + r"(?:=" + DATE + r")?)"
    r"(?P<sp1>[ \t]+)"
    r"(?:(?P<status>[!*])(?P<sp2>[ \t]+))?"
    r"(?P<desc>[^;]*?)"
    r"(?P<tail>[ \t]*;.*)?$"
)
# hledger requires two or more spaces (or a tab) between the account and the
# amount. A single space is part of the account name, so this regex must keep
# the same rule or it parses lines differently from hledger.
POSTING_RE = re.compile(
    r"^(?P<indent>[ \t]+)(?P<acct>[^ \t;](?:[^;]*?))"
    r"(?:(?P<gap>[ \t]{2,}|\t[ \t]*)(?P<rest>.*))?$"
)
NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*|-?\.\d+")


class SpecError(Exception):
    """The SPEC file has an error."""


class Rule:
    """One line of the SPEC file."""

    def __init__(self, number, pattern, payee, account, comment):
        self.number = number
        self.pattern = pattern
        self.regex = re.compile(pattern, re.IGNORECASE)
        self.payee = payee
        self.account = account
        self.comment = comment
        self.matches = 0


class Entry:
    """One journal entry: a header line and its posting lines."""

    def __init__(self, lines, start, end, header):
        self.start = start  # index of the header line
        self.end = end  # index after the last line of the entry
        self.header = header  # match of HEADER_RE on the header line
        self.postings = []  # (line index, regex match)
        for index in range(start + 1, end):
            line = strip_eol(lines[index])
            if line.strip().startswith(";"):
                continue
            match = POSTING_RE.match(line)
            if match:
                self.postings.append((index, match))

    @property
    def date(self):
        return self.header.group("date")

    @property
    def description(self):
        return self.header.group("desc").strip()

    @property
    def raw(self):
        """Raw bank text: the header comment, or the description."""
        tail = self.header.group("tail")
        comment = tail.split(";", 1)[1].strip() if tail else ""
        return comment or self.description

    @property
    def bare(self):
        return [
            (i, m)
            for i, m in self.postings
            if m.group("acct").strip() == BARE_ACCOUNT
        ]

    def amount_of(self, match):
        """Return the Decimal amount of a posting, or None if unknown."""
        rest = (match.group("rest") or "").split(";", 1)[0].strip()
        found = NUMBER_RE.search(rest)
        if found:
            try:
                return Decimal(found.group(0).replace(",", ""))
            except InvalidOperation:
                return None
        if rest:
            return None
        # Elided amount: it balances the other postings.
        total = Decimal(0)
        for _, other in self.postings:
            if other is match:
                continue
            value = self.amount_of_explicit(other)
            if value is None:
                return None
            total += value
        return -total

    def amount_of_explicit(self, match):
        rest = (match.group("rest") or "").split(";", 1)[0]
        found = NUMBER_RE.search(rest)
        if not found:
            return None
        return Decimal(found.group(0).replace(",", ""))


def strip_eol(line):
    return line.rstrip("\r\n")


def read_lines(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return handle.read().splitlines(keepends=True)


def parse_entries(lines):
    """Return the Entry list. An entry starts at a dated line."""
    entries = []
    index = 0
    while index < len(lines):
        header = HEADER_RE.match(strip_eol(lines[index]))
        if header:
            end = index + 1
            while end < len(lines) and lines[end][:1] in (" ", "\t"):
                end += 1
            entries.append(Entry(lines, index, end, header))
            index = end
        else:
            index += 1
    return entries


def merchant_key(raw):
    """Return the group key for a raw bank text."""
    text = raw.strip()
    for prefix in KEY_PREFIXES:
        if text.upper().startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = re.sub(r"\s+\d.*$", "", text)
    return text[:KEY_MAX].strip()


# --- list mode ------------------------------------------------------------


def money(value):
    return f"{value:,.2f}"


def run_list(journal, top):
    entries = parse_entries(read_lines(journal))
    rows = []  # (entry, amount)
    for entry in entries:
        bare = entry.bare
        if not bare:
            continue
        amounts = [entry.amount_of(match) for _, match in bare]
        amount = sum((a for a in amounts if a is not None), Decimal(0))
        rows.append((entry, amount))

    print(f"Uncategorized entries: {len(rows)}   Sum: {money(sum(a for _, a in rows))}")
    print()
    months = Counter()
    for entry, _ in rows:
        month = re.sub(r"[/.]", "-", entry.date)[:7]
        months[month] += 1
    print("By month:")
    for month in sorted(months):
        print(f"  {month}  {months[month]}")
    print()

    groups = {}
    one_offs = []
    for entry, amount in rows:
        reasons = []
        if abs(amount) > LARGE_AMOUNT:
            reasons.append("over 1000")
        if CHECK_RE.match(entry.raw):
            reasons.append("check")
        if amount < 0:
            reasons.append("income-like")
        if reasons:
            one_offs.append((entry, amount, ", ".join(reasons)))
            continue
        group = groups.setdefault(merchant_key(entry.raw), [0, Decimal(0)])
        group[0] += 1
        group[1] += amount

    ordered = sorted(groups.items(), key=lambda item: abs(item[1][1]), reverse=True)
    print(f"Merchant groups ({len(ordered)}, top {min(top, len(ordered))}):")
    print(f"  {'rows':>5}  {'total':>12}  key")
    for key, (count, total) in ordered[:top]:
        print(f"  {count:>5}  {money(total):>12}  {key}")
    print()
    print(f"One-off / needs input ({len(one_offs)}, not in the groups above):")
    for entry, amount, reason in one_offs:
        print(f"  {entry.date}  {money(amount):>12}  [{reason}]  {entry.raw[:60]}")
    return 0


# --- apply mode -----------------------------------------------------------


def read_spec(path):
    rules = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) not in (3, 4) or not all(f for f in fields[:3]):
                raise SpecError(
                    f"{path}:{number}: need REGEX<TAB>PAYEE<TAB>ACCOUNT[<TAB>COMMENT]"
                )
            comment = fields[3] if len(fields) == 4 else ""
            try:
                rules.append(Rule(number, fields[0], fields[1], fields[2], comment))
            except re.error as error:
                raise SpecError(f"{path}:{number}: bad regex: {error}") from error
    return rules


def rewrite_header(entry, lines, payee):
    """Return the new header line with the payee replaced."""
    header = entry.header
    tail = header.group("tail")
    if tail is None:
        tail = "  ; " + entry.raw
    status = (header.group("status") + header.group("sp2")) if header.group("status") else ""
    eol = lines[entry.start][len(strip_eol(lines[entry.start])):]
    return header.group("date") + header.group("sp1") + status + payee + tail + eol


def rewrite_posting(line, match, account, comment):
    """Return the posting line with the account replaced."""
    eol = line[len(strip_eol(line)):]
    gap = match.group("gap")
    rest = match.group("rest")
    new = match.group("indent") + account
    if rest is not None:
        if "\t" not in gap:
            gap = " " * max(2, len(gap) - (len(account) - len(BARE_ACCOUNT)))
        new += gap + rest
    if comment:
        new = new.rstrip() + "  ; " + comment
    return new + eol


def apply_rules(lines, rules):
    """Return (new_lines, changed_entries, skipped, already_done)."""
    new_lines = list(lines)
    changed = []
    skipped = []
    already_done = 0
    for entry in parse_entries(lines):
        raw = entry.raw
        rule = next((r for r in rules if r.regex.search(raw)), None)
        if rule is None:
            continue
        bare = entry.bare
        if len(bare) == 0:
            already_done += 1
            continue
        if len(bare) > 1:
            skipped.append(entry)
            continue
        rule.matches += 1
        index, match = bare[0]
        new_lines[index] = rewrite_posting(lines[index], match, rule.account, rule.comment)
        if rule.payee != "-":
            new_lines[entry.start] = rewrite_header(entry, lines, rule.payee)
        changed.append(entry)
    return new_lines, changed, skipped, already_done


def hledger(*args):
    """Run hledger. Return (exit code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["hledger", *args], capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return 124, "", "hledger timed out"
    return result.returncode, result.stdout, result.stderr


def balances(journal):
    code, out, err = hledger("-f", journal, "bal", "Assets", "Liabilities", "-N")
    if code != 0:
        raise RuntimeError(err.strip() or "hledger bal failed")
    return out


def make_backup(journal):
    """Copy the journal to /tmp/<name>.<timestamp>.bak. Never overwrite."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = os.path.basename(journal)
    counter = 0
    while True:
        suffix = "" if counter == 0 else f"-{counter}"
        path = f"{BACKUP_DIR}/{name}.{stamp}{suffix}.bak"
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            counter += 1
            continue
        os.close(handle)
        shutil.copyfile(journal, path)
        return path


def payee_blocks(rules, rules_path):
    """Return (new block texts, skipped patterns) for the payees rules file."""
    existing = set()
    if os.path.exists(rules_path):
        with open(rules_path, encoding="utf-8") as handle:
            existing = {line.rstrip("\r\n") for line in handle}
    blocks = []
    skipped = []
    for rule in rules:
        if rule.payee == "-" and rule.comment:
            continue  # one-off: no block
        head = f"if %rawdesc {rule.pattern}"
        if head in existing:
            skipped.append(rule.pattern)
            continue
        existing.add(head)
        body = [head]
        if rule.payee != "-":
            body.append(f"    description {rule.payee}")
        body.append(f"    account1 {rule.account}")
        blocks.append("\n".join(body))
    return blocks, skipped


def append_blocks(rules_path, blocks):
    with open(rules_path, newline="", encoding="utf-8") as handle:
        text = handle.read()
    heading = f"# --- Added {datetime.now().strftime('%Y-%m')} (user-approved categories) ---"
    addition = "" if text.endswith("\n") or not text else "\n"
    if heading not in text.splitlines():
        addition += "\n" + heading + "\n\n"
    addition += "\n\n".join(blocks) + "\n"
    with open(rules_path, "a", newline="", encoding="utf-8") as handle:
        handle.write(addition)


def run_apply(journal, rules, dry_run, rules_path):
    if rules_path is not None and not os.path.exists(rules_path):
        print(f"ERROR: no such file: {rules_path}", file=sys.stderr)
        return 2
    lines = read_lines(journal)
    new_lines, changed, skipped, already_done = apply_rules(lines, rules)

    print(f"{'Dry run: ' if dry_run else ''}rule matches:")
    for rule in rules:
        print(f"  {rule.matches:>4}  line {rule.number}: {rule.pattern}")
    print(f"Total entries to change: {len(changed)}")
    zero = [r for r in rules if r.matches == 0]
    if zero:
        print("Rules with zero matches:")
        for rule in zero:
            print(f"  line {rule.number}: {rule.pattern}")
    if already_done:
        print(f"Matched a rule but have no bare Expenses posting (not touched): {already_done}")
    for entry in skipped:
        print(f"Skipped (2 or more bare Expenses postings): line {entry.start + 1}: {entry.raw[:60]}")

    blocks = []
    if rules_path:
        blocks, dup = payee_blocks(rules, rules_path)
        print(f"Payee rules: {len(blocks)} to add, {len(dup)} already in {rules_path}")
        for pattern in dup:
            print(f"  skipped existing: if %rawdesc {pattern}")

    if dry_run:
        return 0
    if zero:
        print(
            "ERROR: a rule has no entry to change (no match, already"
            " categorized, or skipped). Nothing changed.",
            file=sys.stderr,
        )
        return 2

    if new_lines != lines:
        code, _, err = hledger("-f", journal, "check")
        if code != 0:
            print(f"ERROR: journal check fails before the change. Nothing changed.\n{err}", file=sys.stderr)
            return 1
        try:
            before = balances(journal)
        except RuntimeError as error:
            print(f"ERROR: {error}. Nothing changed.", file=sys.stderr)
            return 1
        backup = make_backup(journal)
        try:
            with open(journal, "w", newline="", encoding="utf-8") as handle:
                handle.write("".join(new_lines))
        except OSError as error:
            try:
                shutil.copyfile(backup, journal)
                restored = f"The journal was restored from {backup}"
            except OSError as restore_error:
                restored = f"RESTORE FAILED: {restore_error}. Recover from {backup}."
            print(f"ERROR: could not write the journal: {error}\n{restored}", file=sys.stderr)
            return 1
        try:
            code, _, err = hledger("-f", journal, "check")
            problem = None
            if code != 0:
                problem = f"hledger check failed:\n{err}"
            elif balances(journal) != before:
                problem = "Asset or liability balances changed."
        except RuntimeError as error:
            problem = str(error)
        if problem:
            shutil.copyfile(backup, journal)
            print(f"ERROR: {problem}\nThe journal was restored from {backup}", file=sys.stderr)
            return 1
        print(f"Journal changed. Check passed. Balances unchanged. Backup: {backup}")
    else:
        print("Journal not changed.")

    if blocks:
        append_blocks(rules_path, blocks)
        print(f"Appended {len(blocks)} block(s) to {rules_path}")
    return 0


# --- verify mode ----------------------------------------------------------


def normalized_entries(text, rules):
    """Return a list of (date, header, postings) for entries that match a rule."""
    result = []
    for entry in parse_entries(text.splitlines(keepends=True)):
        if not any(r.regex.search(entry.raw) for r in rules):
            continue
        status = entry.header.group("status") or ""
        header = " ".join(f"{status} {entry.description}".split())
        postings = tuple(
            sorted(
                " ".join(
                    (m.group("acct") + " " + (m.group("rest") or "").split(";", 1)[0]).split()
                )
                for _, m in entry.postings
            )
        )
        result.append((entry.date.replace("/", "-").replace(".", "-"), header, postings))
    return result


def run_verify(journal, converted, rules):
    code, printed, err = hledger("-f", journal, "print")
    if code != 0:
        print(f"ERROR: hledger print failed:\n{err}", file=sys.stderr)
        return 2
    with open(converted, encoding="utf-8") as handle:
        converted_text = handle.read()
    from_rules = normalized_entries(converted_text, rules)
    from_journal = normalized_entries(printed, rules)
    if from_rules:
        low = min(e[0] for e in from_rules)
        high = max(e[0] for e in from_rules)
        from_journal = [e for e in from_journal if low <= e[0] <= high]
    rules_count = Counter(from_rules)
    journal_count = Counter(from_journal)
    only_rules = rules_count - journal_count
    only_journal = journal_count - rules_count
    print(f"Compared {len(from_rules)} converted and {len(from_journal)} journal entries.")
    print(f"Only in rules: {sum(only_rules.values())}   Only in journal: {sum(only_journal.values())}")
    for label, diff in (("only in rules", only_rules), ("only in journal", only_journal)):
        for (date, header, postings), count in list(diff.items())[:10]:
            print(f"  {label} x{count}: {date} {header} | {'; '.join(postings)}")
    return 0 if not only_rules and not only_journal else 1


# --- main -----------------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Summarize and bulk-categorize journal entries that post to bare Expenses."
    )
    parser.add_argument("--journal", required=True, help="journal file")
    parser.add_argument("--list", action="store_true", help="summarize bare Expenses entries")
    parser.add_argument("--top", type=int, default=25, help="merchant groups to show (default 25)")
    parser.add_argument("--apply", metavar="SPEC.tsv", help="apply the rules in SPEC.tsv")
    parser.add_argument("--dry-run", action="store_true", help="with --apply: count only")
    parser.add_argument("--payees-rules", metavar="PATH", help="with --apply: append rule blocks to PATH")
    parser.add_argument("--verify-against", metavar="CONVERTED.journal", help="compare with hledger print output")
    parser.add_argument("--spec", metavar="SPEC.tsv", help="with --verify-against: regexes to use")
    args = parser.parse_args(argv)
    if not (args.list or args.apply or args.verify_against):
        parser.error("give --list, --apply, or --verify-against")
    if args.payees_rules and not args.apply:
        parser.error("--payees-rules needs --apply")
    if args.verify_against and not (args.spec or args.apply):
        parser.error("--verify-against needs --spec or --apply")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not os.path.isfile(args.journal):
        print(f"ERROR: no such file: {args.journal}", file=sys.stderr)
        return 2
    try:
        spec_path = args.apply or args.spec
        rules = read_spec(spec_path) if spec_path else []
    except (SpecError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if (args.apply or args.verify_against) and shutil.which("hledger") is None:
        print("ERROR: hledger is not installed", file=sys.stderr)
        return 2

    status = 0
    if args.list:
        status = run_list(args.journal, args.top)
    if args.apply and status == 0:
        status = run_apply(args.journal, rules, args.dry_run, args.payees_rules)
    if args.verify_against and status == 0:
        status = run_verify(args.journal, args.verify_against, rules)
    return status


if __name__ == "__main__":
    sys.exit(main())
