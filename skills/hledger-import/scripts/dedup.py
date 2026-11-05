#!/usr/bin/env python3
"""Split candidate CSV transactions into keep and skip lists.

A candidate already exists in the journal when the journal has a transaction
with the same date, the same bank-account posting amount, and the same raw
description. Matching is count-based: each journal transaction matches at most
one candidate.

Inputs are two files in the CSV format of "hledger print -O csv":

  --candidate  hledger print -f FILE.csv --rules-file RULES -O csv
  --journal    hledger -f JOURNAL print acct:ACCOUNT -O csv

Output is one JSON object on stdout.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

NEAR_MISS_DAYS = 3


@dataclass
class Entry:
    """One transaction, reduced to its bank-account posting."""

    index: int
    date: str
    amount: Decimal
    text: str

    @property
    def key(self):
        return (self.date, self.amount, self.text)

    def as_dict(self):
        return {
            "index": self.index,
            "date": self.date,
            "amount": format(self.amount, "f"),
            "text": self.text,
        }


def collapse_spaces(text):
    """Return text with runs of whitespace replaced by one space."""
    return " ".join(text.split())


def read_entries(path, account):
    """Read an hledger CSV file. Return one Entry per transaction.

    The amount is the sum of the postings on ACCOUNT. The text is the
    transaction comment, or the description when there is no comment.
    A transaction with no posting on ACCOUNT is ignored.
    """
    totals = {}
    meta = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["account"] != account:
                continue
            index = int(row["txnidx"])
            totals[index] = totals.get(index, Decimal(0)) + Decimal(row["amount"])
            text = collapse_spaces(row["comment"]) or collapse_spaces(
                row["description"]
            )
            meta[index] = (row["date"], text)
    return [
        Entry(index, meta[index][0], totals[index], meta[index][1])
        for index in sorted(totals)
    ]


def days_apart(first, second):
    """Return the absolute number of days between two ISO dates."""
    return abs((date.fromisoformat(first) - date.fromisoformat(second)).days)


def split_entries(candidates, journal):
    """Return (keep, skip, unused_journal) for the given entries."""
    available = defaultdict(list)
    for entry in journal:
        available[entry.key].append(entry)
    keep = []
    skip = []
    for candidate in candidates:
        matches = available[candidate.key]
        if matches:
            matches.pop(0)
            skip.append(candidate)
        else:
            keep.append(candidate)
    unused = [entry for matches in available.values() for entry in matches]
    return keep, skip, unused


def find_near_misses(keep, unused):
    """Pair kept candidates with unmatched journal entries.

    A near miss has the same amount and text, and a date within
    NEAR_MISS_DAYS days or in the same calendar month.
    """
    misses = []
    for candidate in keep:
        for entry in unused:
            if (
                entry.amount == candidate.amount
                and entry.text == candidate.text
                and (
                    days_apart(entry.date, candidate.date) <= NEAR_MISS_DAYS
                    or entry.date[:7] == candidate.date[:7]
                )
            ):
                misses.append(
                    {"candidate": candidate.as_dict(), "journal": entry.as_dict()}
                )
    return misses


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Split candidate CSV transactions into keep and skip lists."
    )
    parser.add_argument("--candidate", required=True, help="candidate CSV file")
    parser.add_argument("--journal", required=True, help="journal CSV file")
    parser.add_argument("--account", required=True, help="bank account name")
    parser.add_argument(
        "--indexes",
        action="store_true",
        help="also output keep_indexes, the txnidx values of kept candidates",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    candidates = read_entries(args.candidate, args.account)
    journal = read_entries(args.journal, args.account)
    keep, skip, unused = split_entries(candidates, journal)
    result = {
        "keep": [entry.as_dict() for entry in keep],
        "skip": [entry.as_dict() for entry in skip],
        "near_misses": find_near_misses(keep, unused),
    }
    if args.indexes:
        result["keep_indexes"] = [entry.index for entry in keep]
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
