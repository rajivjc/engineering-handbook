# Convention guard tests

**Category:** universal
**Applies to:** any “we never do X” rule in a codebase, where X is a recognizable code shape.

## Problem

Every codebase has rules that aren’t captured by the type system. “Never hardcode a timezone string”; “Don’t import from `src/competitions/` outside the allowed integration files”; “Don’t use `any` in test files”; “All database tables in module `comp_` must be prefixed `comp_`.”

These rules survive as long as the team remembers them. When the team grows, when a contributor joins, when the original author moves on — the rules erode silently. Six months later, someone greps the codebase and finds twelve violations of a rule everyone “agreed” not to break.

The fix is to encode the rule as a test.

## Mechanism

A convention guard test has four parts:

1. **A set of forbidden patterns.** Strings, regexes, or AST shapes that match the violation.
2. **An allow-list with reasons.** Every legitimate exception is enumerated with a short justification.
3. **A grep-like search across the codebase.** Find all matches; subtract allow-listed entries; flag the remainder.
4. **A clear failure message.** When the test fails, the message tells the contributor exactly what’s wrong and how to fix it.

```ts
// tests/conventions/no-hardcoded-timezone.spec.ts
import { execSync } from 'node:child_process'

const FORBIDDEN_PATTERNS = [
  "'Asia/Singapore'",
  '"Asia/Singapore"',
  "'+08:00'",
]

const ALLOW_LIST: { file: string; reason: string }[] = [
  { file: 'src/lib/club.ts', reason: 'build-time fallback when DB is unreachable' },
  { file: 'src/lib/timezone.ts', reason: 'documented helper default' },
  { file: 'src/components/admin/SettingsForm.tsx', reason: 'placeholder text in form input' },
]

function findViolations(): { file: string; line: number; pattern: string }[] {
  const violations: { file: string; line: number; pattern: string }[] = []
  for (const pattern of FORBIDDEN_PATTERNS) {
    const cmd = `grep -rn "${pattern.replace(/"/g, '\\"')}" src/ --include='*.ts' --include='*.tsx' || true`
    const output = execSync(cmd, { encoding: 'utf-8' }).trim()
    if (!output) continue
    for (const line of output.split('\n')) {
      const [file, lineNum] = line.split(':', 2)
      if (ALLOW_LIST.some(entry => file.endsWith(entry.file))) continue
      // Skip default-parameter syntax (= 'Asia/Singapore') and ?? coalescence
      if (/=\s*['"]/.test(line) || /\?\?\s*['"]/.test(line)) continue
      violations.push({ file, line: parseInt(lineNum), pattern })
    }
  }
  return violations
}

describe('timezone hardcoding guard', () => {
  it('no hardcoded timezone strings outside the allow-list', () => {
    const violations = findViolations()
    if (violations.length === 0) return

    const message = [
      `Found ${violations.length} hardcoded timezone reference(s) outside the allow-list:`,
      ...violations.map(v => `  ${v.file}:${v.line}: ${v.pattern}`),
      '',
      'How to fix:',
      "  - Server code: use getClub().timezone",
      "  - Client code: use useClubConfig().timezone",
      '  - If this file should be allow-listed, add to ALLOW_LIST with a reason',
    ].join('\n')
    throw new Error(message)
  })
})
```

The shape generalizes. The `FORBIDDEN_PATTERNS` change per rule. The `ALLOW_LIST` shape stays the same. The failure message changes.

## Examples of rules that work as guard tests

- **No hardcoded timezones / locales.** Patterns: `'Asia/Singapore'`, `'en-SG'`, `+08:00`. Allow-list: a small set of build-time fallback files.
- **Module boundaries.** Patterns: imports from outside a module to inside it (or vice versa). Allow-list: explicit integration file paths.
- **No `any` in tests.** Pattern: `: any` or `as any`. Allow-list: rare exceptions for third-party type gaps.
- **No `dangerouslySetInnerHTML`.** Pattern: the literal string. Allow-list: known sanitized renderers.
- **No `console.log`.** Pattern: `console.log(`. Allow-list: scripts directory.
- **All migration files have a forward and reverse.** Pattern: file in `migrations/` without a corresponding `.down.sql` peer.
- **All public-facing routes have a `<Suspense>` boundary.** Pattern: pages in `app/` whose default export doesn’t include `Suspense`.

The rules are project-specific. The pattern is universal.

## Anti-patterns

**Allow-list without reasons.** When the next person sees an entry, they don’t know if it’s load-bearing or accidental. Every entry must carry a justification.

**Allow-list that grows without review.** Convention guards earn their keep when the allow-list is reviewed, not when it’s a dumping ground. Periodic audit: are these still valid? Can any of them be eliminated?

**Patterns that are too permissive.** “Anything containing `Singapore`” matches comments, test fixtures, and documentation. The forbidden patterns must be specific enough to identify real violations and not flag legitimate uses.

**Patterns that are too strict.** “No `+08:00` anywhere” catches `+08:00` in unrelated math expressions. Tighten the pattern (e.g., `'+08:00'` with quotes) or use AST-based detection for high-stakes rules.

**Failure messages that don’t tell you how to fix the violation.** A test that says “guard rail failed” without naming the rule, the file, the line, and the fix is a test that gets disabled the first time someone hits it under deadline.

## Why grep and not AST

For most rules, regex over source files is adequate and ten times faster to implement than an AST parser. The cases where AST is worth the investment:

- The rule depends on syntactic context that’s hard to grep (e.g., “no top-level `await` in `app/` files”).
- The forbidden pattern is common as text but rare as actual code (e.g., the literal word `password` in many comments but as a variable name only in security-relevant code).
- The codebase is large enough that the regex’s false-positive rate becomes a maintenance burden.

For the typical case — a string or shape that should never appear in source — grep + regex + an allow-list is the pragmatic answer.

## Negative consequences

- **The allow-list ages.** Files get renamed, refactored out of existence, or replaced. The allow-list still references them. Periodic cleanup is required.
- **False positives are demoralizing.** If the test fires on legitimate code, contributors learn to ignore it or auto-add to the allow-list. Calibrate the patterns carefully.
- **Convention guards are slower than unit tests.** Grepping the source tree takes a second or two; unit tests take milliseconds. For dozens of rules, the cumulative cost adds to CI time. Mitigation: run guards in a separate test suite that the IDE doesn’t auto-run on every save.
- **The discipline doesn’t apply to all rules.** “Code should be clear” isn’t a guard test; it’s code review. Some rules genuinely need human judgment. The pattern is for rules where the violation is a recognizable shape, not for rules where the violation is “this code is hard to read.”

## Verification

Add a deliberate-violation step to every convention guard’s setup:

1. Add a known violation to a non-allow-listed file.
2. Run the test. Confirm it fails with a message identifying the violation.
3. Remove the violation. Confirm green.
4. Add the violation to an allow-listed file. Confirm green (the allow-list works).

This proves the test engages with real code. Skip this step and you have a guard that might pass for the wrong reasons.

## Related

- `module-boundary-tests-with-grep` for the specific case of module-import boundaries.
- `deliberate-violation-verification` for the discipline of proving the guard catches real violations.
