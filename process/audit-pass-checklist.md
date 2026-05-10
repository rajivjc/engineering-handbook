# Audit pass checklist

**Category:** process
**Applies to:** any session-based workflow where execution is followed by an audit phase, especially when an AI coding agent did the execution.

## Problem

The audit phase of a session is where bugs get caught before they ship. But “audit the diff” is a vague instruction. A reviewer who reads the diff cold, without structure, will:

- Spot the obvious issues and miss the subtle ones.
- Spend time on style nits while a logic bug slips through.
- Fail to catch out-of-scope changes that don’t appear obviously wrong.
- Approve sessions that “look fine” but didn’t run the verification gate.
- Not notice when a session’s diff diverges from its spec.

The fix: an audit checklist that names *what to check* in *what order*. Following it isn’t sufficient for a great audit, but skipping it is sufficient for a bad one. Structured audits catch a different class of issue than unstructured ones.

## Mechanism

The checklist runs in three passes: scope, mechanics, content. Each pass produces findings; findings get classified.

### Pass 1: Scope (does the diff match the spec?)

```
1.  Clone the repo fresh; check out the commit being audited.
2.  Run `git log --oneline -10` to confirm the commit history matches expectation
    (one new commit on main; previous sessions still in place).
3.  Run `git diff --stat <parent>..<commit>`. Read the file list.
4.  Open the spec. Compare:
    - Every file in the spec's deliverables list appears in the diff. (No missing work.)
    - Every file in the diff appears in the spec's deliverables list, OR is
      explicitly authorized by a constraint (e.g., "may also touch X if Y").
      (No out-of-scope work.)
    - File counts match. ("Spec said 12 files; diff has 12 files.")
5.  For sessions that explicitly named "do not touch" files: confirm the diff
    does not modify them.
```

The first pass is mechanical. It catches the most common audit finding: the agent got distracted and changed something it shouldn’t have, or skipped something it should have. Nothing else matters until the scope is right.

### Pass 2: Mechanics (did verification pass?)

```
6.  In the session's reported output, find the four-step gate result.
    Confirm all four steps exited zero (typecheck, build, lint, tests).
7.  Re-run the gate locally against the audited commit. Confirm same result.
    (CI parity: trust but verify.)
8.  Inspect test counts. Compare before-session vs. after-session.
    A drop without a stated reason is a finding.
9.  For sessions that mandate deliberate-violation passes: confirm the
    spec's verification section was followed and the agent reported the
    pass-fail-pass cycle.
10. Lint warnings: are there new ones? Are they accepted? Are they suppressed
    silently?
```

Mechanics catches drift between “what the agent reported” and “what’s actually true.” Most commonly: the agent ran the gate, reported success, but a test was added that doesn’t actually test anything (passes vacuously); or a lint warning was suppressed via `// eslint-disable-next-line` without justification.

### Pass 3: Content (is the work right?)

```
11. For each file in the diff, by domain group:
    - Data layer (migrations, schema, RPCs, fixtures)
    - Action layer (server actions, route handlers, mutations)
    - Component layer (UI, presentation logic)
    - Test layer (specs, fixtures, harnesses)
    - Documentation (README, ADRs, pattern docs)
12. Read each diff in context. Watch for:
    - Logic that contradicts the spec.
    - Missing error paths.
    - Authorization checks at only one layer (RLS but not action, or vice versa).
    - Mock-mode parity violations.
    - Hardcoded values that should be configurable.
    - Dependency additions not authorized by the spec.
13. For content-heavy sessions (handbook, documentation): byte-fidelity check.
    Compare each file's content against the source draft (if available).
    Flag substantive differences; cosmetic differences (whitespace, quote
    style) noted but not blockers.
14. Cross-reference resolution: any link from the new files to other files
    in the repo — does the target exist? Are forward references explicitly
    tagged as such?
15. For pattern docs or skill files: do the code examples actually work?
    Type-check at least the load-bearing examples.
```

The content pass is where engineering judgment matters most. The first two passes are checklist-driven; the third requires understanding the work.

## Classifying findings

Every finding is one of three categories:

- **Blocker.** Ship-stopping. The session isn’t done until this is resolved. Examples: missing test coverage on a load-bearing function, an authorization check at the action layer but not the database, a migration that won’t apply to the production DB.
- **Nit.** Worth fixing, but doesn’t block. Cosmetic, minor, future cleanup. Examples: inconsistent naming, missing JSDoc, slightly suboptimal SQL. Note in the audit; don’t require a fix-up session.
- **Accepted.** Known issue, deferred deliberately. The audit notes it and the rationale; the team agrees not to fix it now. Examples: an N+1 query that’s fine for current data volume; a test that’s slow but reliable; an inconsistency that the next session will resolve.

A clean audit has zero blockers, some nits, and a handful of accepted items. A blocker count > 0 means a fix-up session is needed before declaring done.

### Format of an audit output

```markdown
## Audit: Session N (commit <hash>)

**Verdict:** SHIP | FIX-UP NEEDED

### Pass 1: Scope
- Spec listed 12 files; diff has 12 files. ✓
- All do-not-touch files preserved. ✓
- ...

### Pass 2: Mechanics
- Four-step gate: PASSED locally and in CI. ✓
- Test count: 484 → 491 (+7, expected per spec). ✓
- ...

### Pass 3: Content
[Per-file or per-group findings]

### Findings
**Blockers (0):**

**Nits (3):**
- patterns/web/foo.md, line 42: trailing whitespace
- ...

**Accepted (1):**
- N+1 query in tournament detail page; current data volume tolerates it; tracked for Session N+2.
```

The structure is the load-bearing piece. Whatever findings exist, the format makes them findable and addressable.

## Why three passes and not one

A single-pass read of a diff invites confirmation bias: you’re looking for problems while also building a mental model of the work. The two activities interfere.

Splitting the audit into scope → mechanics → content lets each pass focus narrowly:

- **Scope** is mechanical: file lists, do-not-touch lists, spec comparison. Doesn’t require understanding the code.
- **Mechanics** is verification: the gate ran, tests passed. Doesn’t require understanding the code either.
- **Content** is the engineering review. By the time you reach it, you’ve already confirmed the diff is *eligible* for review — it’s the right scope, the verification passed. Now you can focus on whether the work is right.

Reversing the order (read content first) leads to spending cognitive budget on a diff that turns out to have wrong scope or failed verification. Not every commit needs deep content review; every commit needs scope and mechanics check.

## Anti-patterns

**Auditing without the spec in hand.** “Does this look fine?” — without the contract, you’re reading the diff cold. The audit is fundamentally a comparison: spec vs. diff. Without one side, no comparison.

**Reading the diff sequentially in random order.** Read by domain group (data → action → component → test → docs). The relationships between layers are easier to see when you read a layer at a time. Random-order reading misses cross-layer issues.

**Approving on green CI alone.** CI confirms the gate passed. It doesn’t confirm the work is right or in scope. The audit must include human review of the diff.

**Skipping deliberate-violation pass verification.** If the spec required a deliberate-violation pass for a new test, the audit must confirm it was actually performed. Otherwise the test could be vacuously passing.

**Vague findings.** “This part is concerning.” → not actionable. Specify the file, the line, the concern, the suggested resolution. The author has to know what to do.

**Bundling many findings into one comment.** Each finding is a separate item. Bundling makes it harder for the author to address them one at a time and for future readers to find specific issues.

**Auditing changes you wrote yourself.** Bias is unavoidable. For solo work, accept that self-audit is weaker; pair it with stronger automation (more tests, more guards, more deliberate-violation passes). For team work, never self-audit security-sensitive changes.

**No follow-up on accepted items.** “Accepted, will fix later” with no tracking → forever-deferred. Each accepted item should have a destination: a backlog item, a future session’s spec, an ADR documenting the deferral.

## Negative consequences

- **Audits take time.** A 12-file session might take 30–90 minutes to audit thoroughly. For high-velocity projects, this is real overhead.
- **The checklist can become rote.** If you stop *thinking* and just check boxes, you’ll miss issues the checklist doesn’t cover. The structure is the floor, not the ceiling.
- **Findings can pile up.** Many small nits across many sessions create a backlog. Either dispatch them periodically or accept they become tech debt.
- **Self-audits are weaker than peer audits.** Even with the structure, you’ll miss issues in your own work. Compensate with automation.

## Verification

The audit verifies the session. There’s no separate “verification of the audit.”

What can be tracked over time:

- **False-positive rate.** Findings raised, then determined to be non-issues. Calibrates the audit’s sensitivity.
- **Issue recurrence.** Did issue X appear in Session A, get fixed, then reappear in Session C? Indicator the fix wasn’t durable, or the agent didn’t learn from it.
- **Audit consistency.** Different auditors (or the same auditor at different times) finding similar issues on similar diffs. Inconsistency suggests the checklist needs work.

## Related

- `process/spec-execute-audit-loop.md` — the audit phase is one part of the larger loop.
- `process/four-step-verification-gate.md` — what the mechanics pass verifies ran.
- `process/session-prompt-template.md` — the spec is the contract the audit checks against.
- `process/single-commit-per-session.md` — single-commit makes the audit’s diff scope unambiguous.
