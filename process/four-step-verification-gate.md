# Four-step verification gate

**Category:** process
**Applies to:** any project where a session of work is considered “complete” only after a defined check passes; especially relevant when a coding agent is doing the work and a human is reviewing.

## Problem

A common shape: a session of work edits 30 files, declares done, opens a PR. The reviewer reads the diff, finds it plausible, merges. Three days later, the build is broken in production because:

- A type error wasn’t surfaced until full project compilation (the agent ran a partial check).
- A linter caught a violation that was suppressed locally but fails in CI.
- A test was added that doesn’t actually pass; the agent ran the test once and got a green output that was actually a “no tests collected” result.
- The build command itself failed because of a missing dependency the agent forgot to add to package.json.

The session “felt complete” because each individual concern (types, build, lint, tests) was checked once, but no single command verified them all *together*. Drift between checks is the failure mode.

The fix is a single verification command that runs all four checks in sequence. A session is “complete” only when this command exits zero. No other declaration of doneness counts.

## Mechanism

Define the gate as a single command sequence (a Make target, an npm script, a shell script — anything reproducible):

```bash
# scripts/verify.sh
#!/usr/bin/env bash
set -euo pipefail

echo "==> 1/4: TypeScript typecheck"
npx tsc --noEmit

echo "==> 2/4: Build"
npm run build

echo "==> 3/4: Lint"
npm run lint

echo "==> 4/4: Tests"
npx vitest run

echo "All checks passed."
```

Every session ends with running this script. If any step fails, the session isn’t done. The agent fixes and re-runs; the human reviewer can also run it locally on the branch before merging.

In a Next.js project, `npm run build` already runs the typecheck, so step 1 is sometimes redundant. Keep it anyway: the explicit `tsc --noEmit` runs faster than a full build, surfaces type errors first (often the easiest to fix), and is a sentinel — if the build “passes” but tsc fails, you know the build is hiding a config issue.

In a Python or Go project, the equivalents are `mypy` / `pyright` / `pytest`, or `go vet` / `go build` / `go test`. The principle is unchanged: four orthogonal checks, run as one command.

## Why all four

Each step catches a class of issue the others miss:

- **Typecheck** catches type errors. Necessary because some build pipelines defer or skip strict typechecking for speed.
- **Build** catches integration issues — module resolution, asset pipeline, generated artifacts, env-var references that fail at build time.
- **Lint** catches style and correctness rules the type system doesn’t enforce — unused imports, accessibility violations, dead code, project-specific rules.
- **Tests** catch behavioral regressions and validate that new code does what it claims.

Skipping any one of them creates a class of bug that ships. The four-step gate is exhaustive enough to be load-bearing without being expensive enough to deter use.

## When to run vs. when to defer

The full gate runs:

- At the end of every session, before declaring done.
- Before opening a PR.
- In CI on every push.
- Locally before pushing to a shared branch.

Faster checks during development are fine — `npx vitest <file>` for the test you’re working on, `tsc --noEmit` for the file you just edited. The discipline is that “done” means the *full* gate has passed, not that “the test I wrote passes.”

## Anti-patterns

**Running checks separately and forgetting one.** “I ran the tests; the lint will pass; let me push.” Lint catches something. Push fails. Time wasted. The gate as a single command prevents this.

**Treating warning output as success.** A linter that says “5 warnings” exits zero. Are warnings acceptable? Either configure the linter to fail on warnings (recommended) or have an explicit policy (“warnings reviewed, not yet failing”). Don’t let `verify.sh` exit zero with warnings if the team treats warnings as failures.

**Running the gate on a partial scope.** “I ran tests for the files I changed.” Necessary but not sufficient — your changes might break tests in *other* files (a shared utility, a type definition, a fixture). The full test run is the load-bearing check.

**Letting the gate take 20 minutes.** If the gate is slow enough to skip, it gets skipped. Aim for under 5 minutes total for a typical project. Mitigate slow tests with categorization (`unit` vs `integration`); the unit suite runs in the gate, integration runs in CI.

**Running the gate on stale code.** Run after every meaningful change, not just at the very end. A session that batches all changes and runs the gate only at the end discovers all problems simultaneously, which is hard to disentangle. Run incrementally.

**Build command that succeeds with type errors.** Some build pipelines (esp. with `transpileOnly` configurations) skip type errors for speed. The `tsc --noEmit` step surfaces them. Don’t trust a green build alone.

**Skipping the gate “because the change is small.”** “It’s a one-line README edit; the gate isn’t needed.” Often true; sometimes the README has a code-block that’s tested or referenced by a build step. The gate is fast; run it always.

## Negative consequences

- **Real wall-clock time.** Even a fast gate is 30–120 seconds. For a session of 10 changes, you might run the gate 5+ times. Adds up.
- **CI duplication.** CI runs the same gate on every push, so the local-then-CI flow re-runs the same checks. This is intentional (CI is the trusted runner), but it’s also redundant time spent.
- **The gate definition is itself code that can break.** A typo in `verify.sh`, a flag that’s deprecated, an environment variable that’s not set in CI. The gate must be tested too — usually by running it. The first run after defining it is the verification.
- **Some projects have legitimately slow tests.** Integration tests against real databases can take minutes. Don’t put them in the four-step gate; put them in a separate pre-deploy gate.

## Verification

The gate verifies itself. If it exits zero, the session is done; if it exits non-zero, fix and re-run. There’s no “verification of the verification.”

What you can verify periodically:

1. **Run the gate against a known-bad commit** (deliberately broken types, deliberately failing test). Confirm it fails. If it doesn’t, the gate is broken.
1. **Audit that all four steps run.** A misconfigured `verify.sh` might silently skip a step; the output should explicitly print “1/4,” “2/4,” etc.
1. **Audit CI parity.** The gate locally and the gate in CI should produce the same result on the same commit. If they diverge, one is wrong.

## Related

- `process/spec-execute-audit-loop.md` — the gate is the “verification” of “execute”; the spec defines what’s expected, the gate confirms it works.
- `process/audit-pass-checklist.md` — the audit checks the substance; the gate checks the mechanics.
- `principles/atomic-state.md` — same philosophy applied to verification: a session is either done (gate passed) or not (gate didn’t pass). No partial state.
