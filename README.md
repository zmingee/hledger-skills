# hledger-skills

Agent skills for working with an [hledger](https://hledger.github.io/) personal
ledger. Each skill is a directory with a `SKILL.md` file that follows the
[Agent Skills standard](https://agentskills.io), so the same folder works with
Claude Code, Codex, OpenCode, Cursor, Gemini CLI, Copilot, pi, and other
compatible agents.

## Skills

| Skill | What it does |
|---|---|
| `hledger-import` | Files a downloaded bank or credit card transaction CSV, imports it into the journal with pending status, skips existing transactions, checks the result, and reports a summary. Then proposes new payee rules. |
| `hledger-categorize` | Summarizes entries that post to the bare `Expenses` account, re-categorizes them in bulk after approval, and records the rules for future imports. |
| `hledger-backfill` | Imports history older than the opening-balance entry, moves the opening entry earlier, and adjusts its account lines so later balances stay the same. |
| `hledger-sort-journal` | Sorts the journal by month, source account, and date, and writes comment section headers. Never edits entry text. |

## Requirements

- `hledger` on the PATH
- Python 3 (standard library only) for the bundled scripts

## Install

The skills expect a finance directory with a `hledger/` directory inside it, holding the
journal and `hledger/rules/payees.rules`. On first use, a skill asks for the path of your
finance directory. The institution registry in `hledger-import` is an example; replace it
with your own institutions, accounts, and rules files.

### Git

Clone the repo into a shared skills location. This works with pi, Codex,
Cursor, Gemini CLI, Copilot, and other agents that read `~/.agents/skills`:

```bash
git clone https://github.com/zmingee/hledger-skills ~/.agents/skills/hledger-skills
```

To keep only a few skills, clone to a working directory and copy the skill
directories you want into your agent's skills location.

### npx skills

Install from the repo with the [skills CLI](https://github.com/vercel-labs/skills).
Run this from a project directory:

```bash
npx skills add zmingee/hledger-skills
```

Select the skills and the agents to install them for. Add `-g` to make the
skills available across projects:

```bash
npx skills add zmingee/hledger-skills --skill hledger-import -a claude-code -g
```

## Layout

```text
hledger-skills/
├── README.md
├── LICENSE
├── .gitignore
└── skills/
    ├── hledger-backfill/
    │   └── SKILL.md
    ├── hledger-categorize/
    │   ├── SKILL.md
    │   └── scripts/categorize.py
    ├── hledger-import/
    │   ├── SKILL.md
    │   └── scripts/dedup.py
    └── hledger-sort-journal/
        ├── SKILL.md
        └── scripts/sort_journal.py
```

## License

MIT, see [LICENSE](LICENSE).
