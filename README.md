# Engineering Handbook

Opinionated software engineering practices, written down so they don’t get re-derived every project. Each pattern is paired with a concrete failure mode that motivated it. The credibility comes from evidence, not from the opinions being clever — most of these aren’t. The value is in the assembly, the discipline, and the bug stories.

Extracted from real production projects: a club management platform shipped to a Singapore venue ([Tigress](https://github.com/rajivjc/Tigress) — 1173 tests, ~54k LOC, 27+ structured AI-coding sessions), an LLM-proxy app ([DeFlatter](https://github.com/rajivjc/deflatter)), a running club coordinator ([Kita](https://github.com/rajivjc/kita)), and a negotiation simulator ([TableStakes](https://github.com/rajivjc/tablestakes)). Patterns that show up in two or more of these are universal; patterns specific to one domain are taxonomized accordingly.

## Who this is for

Solo developers and small teams who ship code via AI coding agents (Claude Code, Cursor, Copilot, Aider, etc.) and want to keep engineering discipline as the agent does the typing. The patterns here are what survives audits, not what sounds clever in a blog post.

If you’re building software with an AI coding agent and notice your tests passing whether the bug is fixed or not, your “best practices” docs going stale within a month, or your audit findings repeating across sessions — this is for you.

## What’s here, in 30 seconds

```
principles/        Five non-negotiables: authorization, mock parity,
                   module boundaries, atomic state, single source of truth.

patterns/          ~25 codified patterns, each with the bug story.
  universal/         Apply to most projects.
  test-correctness/  Meta-patterns about tests.
  web/               Next.js + Supabase / Postgres shape.
  llm/               LLM-proxy applications.
  domain/            Specific feature shapes (templates → instances,
                     soft-delete moderation, polymorphic authorship, etc.)

process/           The spec → execute → audit → fix-up loop.
                   Mandatory verification gates. Findings classification.

decisions/         ADR format + worked examples.

security/          OWASP Top 10 for LLM Apps checklist.
                   Threat model template.

case-studies/      Three sanitized audit reports as evidence:
                   a critical RLS leak, an N+1 caught by a regression
                   spy, and an atomicity test that wasn't.

skills/            SKILL.md projections of patterns for agent loading.

onboarding/        Bootstrap a new project from these templates.
```

## One pattern in full

To show what “with the bug story” looks like, here’s the load-bearing one — the meta-pattern this whole handbook is built on:

### Deliberate-violation verification

**Problem.** A test that’s supposed to catch a class of bug only earns trust if you can show it actually fails when the bug is reintroduced. A test that “always passes” is functionally untested. This is true of every guard, every regression spy, every security check.

**The discipline.** For any institutional-memory work — security guards, atomicity tests, regression spies — the audit step **must** include a deliberate-violation pass:

1. Revert the fix you just landed.
1. Run the test.
1. Confirm it fails — and fails for the *right reason*.
1. Restore the fix.

If the test passes when the fix is reverted, the test is broken. The fix doesn’t ship until the test is genuinely engaging.

**The bug story.** Three sessions in a row on a real project shipped tests that passed regardless of whether the underlying fix was working:

- A security guard test that passed because the original regex matched the function name appearing *anywhere* in a policy clause body — including in a side-branch where the rule didn’t apply. The leak the guard was supposed to catch (an `OR`-branch with a bare equality) wasn’t matched. Caught only when someone deliberately reverted the fix and the test passed.
- A CSV precision test that passed regardless of whether the implementation rounded sum-of-rounded or round-of-sum. The test asserted output bytes; both implementations produced the same bytes for the chosen fixture.
- An atomicity test for a multi-step mutation that passed whether the rollback was correct, broken, or absent. The throw was injected at the function-call boundary; no mutation had happened yet, so there was nothing to roll back.

After these three, the discipline became standard practice. Audit time roughly doubled for security-critical changes. The pattern catches a class of bug that no amount of reading-the-test-carefully would.

This is the whole handbook in miniature: a pattern named, the failure mode that motivated it, the discipline that prevents recurrence, and the cost honestly stated.

The full pattern catalogue is in [`patterns/`](patterns/). Each file follows this shape: problem, mechanism, where it’s enforced (specific files and tests), the bug story, deliberate-violation walkthrough.

## Differences from other engineering writing

A few opinionated calls about what this is and isn’t:

- **Not a list of best practices.** “Best practices” lists are the mode collapse of engineering writing. This is a stance, with evidence.
- **Not a tutorial.** If you’re learning Next.js or Postgres, look elsewhere first.
- **Not framework-specific advice.** The patterns work with any agent, any framework with similar primitives. Tigress uses Next.js + Supabase; the patterns generalize to other stacks with the same shape.
- **Not project-specific.** Tigress is the canonical example, but the patterns are not Tigress-shaped. Where a pattern only generalizes within a narrow domain (e.g., LLM-proxy security), it’s tagged that way.
- **Has a bias.** The bias is toward defense-in-depth, automated guards over conventions, and tests that demonstrably catch their target bugs. If you disagree with that bias, this handbook will frustrate you, which is fine.

## How to use it

- **As a reference.** Browse [`patterns/`](patterns/) when you’re solving a specific problem and want to see if there’s a codified shape.
- **As project bootstrapping.** Start with [`onboarding/new-project-bootstrap.md`](onboarding/new-project-bootstrap.md) for a step-by-step setup using the templates.
- **As agent context.** The [`skills/`](skills/) directory contains SKILL.md projections of each pattern. Drop them into a new project’s `.claude/skills/` (or equivalent for your agent) and the agent will load relevant patterns on demand.
- **As an ADR seed.** [`decisions/adr-format.md`](decisions/adr-format.md) is the format I use, with three worked examples in [`decisions/examples/`](decisions/examples/).

## Relationship to GitHub Spec-Kit

Spec-Kit and this handbook overlap in the same neighbourhood — spec-driven development with AI coding agents — but solve different problems. Spec-Kit is tooling and ergonomics; the handbook is discipline and evidence. They layer cleanly. See [`spec-kit-comparison.md`](spec-kit-comparison.md) for the full breakdown including where each is stronger and how to use them together.

## License

MIT. See <LICENSE>.

## Author

Built and used by [Rajiv Cheriyan](https://github.com/rajivjc) across multiple shipped projects. Patterns evolve with practice; old pages don’t get retconned.

If you find a bug in a pattern (a case where it doesn’t generalize, or a counterexample), open an issue — the failure mode is part of the pattern’s value.
