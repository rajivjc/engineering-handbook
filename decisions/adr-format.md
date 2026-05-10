# ADR format

This is the Architecture Decision Record format used across the projects this handbook is extracted from. The discipline that makes ADRs work is mostly in how they’re maintained, not in the format itself.

## The format

```markdown
## ADR-NNN: Title

**Status:** Accepted | Superseded by ADR-MMM
**Date:** YYYY-MM-DD

**Context**
[2–4 sentences on the situation that forced the decision]

**Decision**
[The call, plainly stated]

**Consequences**
[Bullets — both positive and negative. Be honest about tradeoffs]
```

## What the discipline requires

**ADRs are immutable.** When a decision is overturned, write a new ADR that supersedes the old one. Mark the old one’s status as `Superseded by ADR-MMM`. Never edit the original ADR’s content.

This matters because the value of an ADR is the *trail* — what was decided, when, and what was known at the time. An ADR that’s been edited to reflect the current state isn’t an ADR; it’s documentation that happens to have a number.

**Dates are real, not approximate.** Use the date the decision crystallized in code, traceable via `git log`. If the decision predates a clean commit, write `[date approximate]` and explain in the context.

**The Context section names what forced the decision.** Decisions don’t happen in a vacuum. Something pushed against the system. A bug, a performance problem, a regulatory question, a constraint someone surfaced. Name it.

**The Consequences section includes negative consequences.** This is the load-bearing discipline. A consequences section that’s all upside is a signal the ADR isn’t honest yet. Every decision has a cost. The ADR is where you make the cost legible to your future self.

## Anti-patterns

- **The ADR that explains the right answer.** “We chose X because X is better” is not an ADR. It’s a justification. The ADR should make the alternative legible, including why the alternative was tempting.
- **The Consequences section that’s all positive.** Smell. A real decision has a cost. Find the cost. Write it down.
- **The ADR that gets edited when the decision changes.** No. Write a new ADR. Mark the old one superseded. The trail is the value.
- **The ADR with vague status (`Active`, `Living`, `Current`).** ADRs are either `Accepted` or `Superseded by ADR-MMM`. Anything else is a documentation page, not a decision record.
- **Numbering by date or hash.** Sequential integers. ADR-001, ADR-002. Easy to reference, easy to read, hard to confuse.

## Three worked examples

In [`examples/`](examples/), three ADRs from real projects:

- [`mock-mode-required-day-one.md`](examples/mock-mode-required-day-one.md) — a foundational architectural decision with a real ergonomic cost.
- [`deliberate-violation-verification.md`](examples/deliberate-violation-verification.md) — a process discipline written as an ADR after the third repeat of the same audit failure.
- [`self-hosted-vapid-over-third-party.md`](examples/self-hosted-vapid-over-third-party.md) — a build-vs-buy decision with multiple negative consequences honestly listed.

## Why this format and not another

There are several ADR formats in the wild — Michael Nygard’s original, the MADR format, various templates from large engineering organizations. They all do roughly the same thing. This handbook uses a slimmed version because:

- The MADR format has more sections than I find I use (Considered Options, Decision Drivers, Pros and Cons of the Options). For most decisions, two paragraphs of context and a list of consequences is enough.
- The discipline matters more than the schema. An MADR-formatted ADR with no negative consequences is worse than a slim ADR with two negative consequences.
- I want to lower the friction of writing ADRs so they actually get written. The slim format helps.

If your team has standardized on MADR or another format, use that. The point is to use one consistently, with the immutability discipline and the negative-consequences discipline, not which template variant you use.

## Where ADRs live

In a project’s `docs/` directory, typically `docs/DECISIONS.md` or `docs/adr/`. They live in the same repo as the code so they’re versioned with the code. They are not in a wiki, not in Notion, not in a Google Doc. The trail dies if it’s not in the repo.
