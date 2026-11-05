#!/usr/bin/env python3
"""Sort an hledger journal by month, then source account, then date.

Layout of the output file:

  1. Periodic blocks (start with "~"), unchanged, in original order.
  2. "; ===== Opening balance =====" and the opening-balance entries
     (entries with a posting to Equity:Opening Balances).
  3. For each month: "; ===== YYYY-MM =====". For each source account in that
     month: "; ----- YYYY-MM: ACCOUNT -----" and then its entries by date.

The source account is the first Assets: or Liabilities: posting with a
negative amount. If none is negative, it is the first Assets: or Liabilities:
posting. If there is none, it is the first posting.

The script never changes the text of an entry. Generated header lines from an
earlier run are removed before sorting, so a second run gives the same file.
A standalone comment line that is not a generated header stops the sort. The
script backs up the journal first and restores the backup if any verification
fails.
"""

import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

TIMEOUT_SECONDS = 120
OPENING_ACCOUNT = "Equity:Opening Balances"
DATE_START = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")
OPENING_HEADER = "; ===== Opening balance ====="
GENERATED_HEADER = re.compile(
    r"^; ===== (?:Opening balance|\d{4}-\d{2}) =====$"
    r"|^; ----- \d{4}-\d{2}: .+ -----$"
)


class SortError(Exception):
    """A problem that must stop the script."""


def run_hledger(journal, *args):
    """Run hledger on JOURNAL. Return stdout. Raise SortError on failure."""
    command = ["hledger", "-f", journal, *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise SortError("hledger timed out: " + " ".join(command)) from None
    if result.returncode != 0:
        raise SortError(
            "hledger failed: " + " ".join(command) + "\n" + result.stderr.strip()
        )
    return result.stdout


def split_blocks(text):
    """Split text into blocks. A block is a run of non-blank lines."""
    blocks = []
    current = []
    for line in text.split("\n"):
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def is_header(block):
    """Return True for a single-line block that starts with a semicolon."""
    return "\n" not in block and block.startswith(";")


def classify(blocks):
    """Return (periodic, transactions) blocks. Stop on unknown blocks."""
    periodic = []
    transactions = []
    for block in blocks:
        if GENERATED_HEADER.match(block):
            continue
        if is_header(block):
            raise SortError(
                "Standalone comment line that is not a generated header. No file change.\n"
                + block
            )
        if block.startswith("~"):
            periodic.append(block)
        elif DATE_START.match(block):
            transactions.append(block)
        else:
            raise SortError(
                "Block does not start with a date or '~'. No file change.\n"
                + block.split("\n")[0]
            )
    return periodic, transactions


def parse_amount(text):
    """Return the Decimal value of an amount text, or None."""
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def read_transactions(journal):
    """Return a list of (date, source account, is_opening), in file order."""
    output = run_hledger(journal, "print", "-x", "-O", "csv")
    rows_by_index = defaultdict(list)
    for row in csv.DictReader(io.StringIO(output)):
        rows_by_index[int(row["txnidx"])].append(row)
    result = []
    # hledger prints in date order, but txnidx follows the file order.
    for index in sorted(rows_by_index):
        rows = rows_by_index[index]
        result.append(
            (rows[0]["date"], source_account(rows), is_opening(rows))
        )
    return result


def is_opening(rows):
    """Return True when an entry has a posting to the opening account."""
    return any(row["account"] == OPENING_ACCOUNT for row in rows)


def source_account(rows):
    """Return the source account of one entry (see the module docstring)."""
    real = [
        row
        for row in rows
        if row["account"].startswith(("Assets:", "Liabilities:"))
    ]
    for row in real:
        amount = parse_amount(row["amount"])
        if amount is not None and amount < 0:
            return row["account"]
    if real:
        return real[0]["account"]
    return rows[0]["account"]


def build_output(periodic, transactions, infos):
    """Return (new text, new order as a list of original indexes)."""
    entries = list(range(len(transactions)))
    opening = [i for i in entries if infos[i][2]]
    others = [i for i in entries if not infos[i][2]]

    sections = list(periodic)
    order = []

    sections.append(OPENING_HEADER)
    for i in sorted(opening, key=lambda i: (infos[i][0], i)):
        sections.append(transactions[i])
        order.append(i)

    months = sorted({infos[i][0][:7] for i in others})
    for month in months:
        sections.append(f"; ===== {month} =====")
        in_month = [i for i in others if infos[i][0][:7] == month]
        for account in sorted({infos[i][1] for i in in_month}):
            sections.append(f"; ----- {month}: {account} -----")
            chosen = [i for i in in_month if infos[i][1] == account]
            for i in sorted(chosen, key=lambda i: (infos[i][0], i)):
                sections.append(transactions[i])
                order.append(i)
    return "\n\n".join(sections) + "\n", order


def make_backup(journal):
    """Copy JOURNAL to a new backup file. Never overwrite. Return the path."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Backups go to /tmp by design; the path is reported to the user.
    base = f"/tmp/{os.path.basename(journal)}.{stamp}"  # noqa: S108
    with open(journal, "rb") as source:
        data = source.read()
    counter = 0
    while True:
        path = f"{base}.bak" if counter == 0 else f"{base}-{counter}.bak"
        try:
            with open(path, "xb") as target:
                target.write(data)
            return path
        except FileExistsError:
            counter += 1


def snapshot(journal):
    """Return (balances, sorted print blocks) for JOURNAL."""
    run_hledger(journal, "check")
    balances = run_hledger(journal, "bal", "-N")
    printed = sorted(split_blocks(run_hledger(journal, "print", "-x")))
    return balances, printed


def verify(journal, before, text_before):
    """Compare the journal with the state before. Raise SortError on a diff."""
    after = snapshot(journal)
    if after[0] != before[0]:
        raise SortError("Balances changed after sorting.")
    if after[1] != before[1]:
        raise SortError("The set of transactions changed after sorting.")
    with open(journal, encoding="utf-8", newline="") as handle:
        text_after = handle.read()
    old = sorted(b for b in split_blocks(text_before) if not is_header(b))
    new = sorted(b for b in split_blocks(text_after) if not is_header(b))
    if old != new:
        raise SortError("The text of a block changed after sorting.")


def main():
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--journal", required=True, help="path to the journal")
    parser.add_argument(
        "--dry-run", action="store_true", help="show the summary, change nothing"
    )
    args = parser.parse_args()

    if shutil.which("hledger") is None:
        print("Error: hledger is not installed. Install it and try again.")
        return 1
    journal = args.journal
    if not os.path.isfile(journal):
        print(f"Error: journal not found: {journal}")
        return 1

    backup = None
    try:
        with open(journal, encoding="utf-8", newline="") as handle:
            text_before = handle.read()
        before = snapshot(journal)

        periodic, transactions = classify(split_blocks(text_before))
        infos = read_transactions(journal)
        if len(infos) != len(transactions):
            raise SortError(
                f"hledger found {len(infos)} transactions "
                f"but the file has {len(transactions)} date blocks."
            )
        new_text, order = build_output(periodic, transactions, infos)
        moved = sum(1 for new, old in enumerate(order) if new != old)

        if args.dry_run:
            print(
                f"Dry run: {len(order)} transactions, {moved} would move. "
                "No file changed."
            )
            return 0

        backup = make_backup(journal)
        with open(journal, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        verify(journal, before, text_before)
    except (SortError, OSError, UnicodeDecodeError, csv.Error, KeyError,
            ValueError) as error:
        print(f"Error: {error}")
        if backup is not None:
            shutil.copyfile(backup, journal)
            print(f"The backup is restored from {backup}")
        return 1

    print(
        f"Sorted: {len(order)} transactions, {moved} moved. "
        f"Checks passed. Backup: {backup}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
