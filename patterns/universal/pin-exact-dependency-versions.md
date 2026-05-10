# Pin exact dependency versions

**Category:** universal
**Applies to:** any project with package management (npm, yarn, pnpm, pip, cargo, etc.).

## Problem

The conventional shape of a `package.json` is:

```json
{
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.2.0",
    "stripe": "~14.5.0"
  }
}
```

The `^` prefix means “compatible with this version” (any 14.x version ≥14.2.0). The `~` prefix means “approximately this version” (any 14.5.x). Both prefixes leave dependency selection to the package manager at install time.

The argument for: minor and patch releases are supposed to be backwards-compatible, so the latest one is automatically better. Security patches roll in for free. Bug fixes propagate without manual updating.

The argument against: those promises are sometimes broken, and you find out at the worst possible time. A “patch” release that introduces a regression in your CI builds for one developer but not another (depending on when the install ran) is the worst kind of debugging session — local environments differ from each other and from production.

## Mechanism

Pin every dependency to an exact version, no prefixes:

```json
{
  "dependencies": {
    "next": "14.2.15",
    "react": "18.3.1",
    "stripe": "14.5.0"
  },
  "devDependencies": {
    "vitest": "2.1.4",
    "typescript": "5.6.3"
  }
}
```

Lockfiles still serve their purpose — they pin the entire transitive graph — but pinning at the manifest level makes the intent explicit. A reader of the manifest sees what’s in production, exactly. A new contributor running `npm install` gets the same versions every time, regardless of when they cloned the repo.

When you want to update, you update *deliberately*: bump the version in the manifest, run the install, run the verification gate, commit. The update is a discrete event with a commit message and (ideally) a note about what changed.

## Why this earns its keep despite the friction

- **Reproducible builds.** Your local install is identical to your CI install is identical to production’s install. No “works on my machine” caused by a transitive dependency that updated overnight.
- **Updates as deliberate events.** Each version bump is its own commit. If a bump breaks something, `git bisect` finds it. With ranged versions, the breakage might trace to a `npm install` that pulled in a new transitive dependency without changing your manifest at all.
- **Security incident response is faster.** “Are we affected by CVE-X in package Y version Z?” is a question you can answer by reading the manifest. With ranged versions, you have to read the lockfile, and the answer might differ between your dev machine and production.
- **Pressure against churn.** When updating is a deliberate act, you do it less often. This is mostly good — most updates aren’t worth it for a small project. The exceptions (security patches) become explicit decisions.

## What about npm/yarn lockfiles?

Lockfiles already pin the transitive dependency graph. Why pin the manifest too?

Lockfiles pin what was installed *at the time of the last install*. If a teammate runs `npm install` (even without changes to the manifest) on a fresh checkout, the lockfile gets regenerated with whatever the latest matching version is for each ranged dependency. The lockfile ages.

Pinning at the manifest level makes the lockfile-update path explicit: *only* a manifest change should change the lockfile. If `npm install` produces a lockfile diff without a manifest change, something went wrong (or someone manually invoked an update flag).

For projects with strict CI policies, this can be enforced: the CI runs `npm install --frozen-lockfile` and fails if the lockfile would have to change.

## What about updates and security patches?

Updates become a workflow:

1. Identify the package(s) you want to update.
1. Bump the version in the manifest.
1. Run `npm install` to update the lockfile.
1. Run the four-step verification gate (typecheck, build, lint, test).
1. Manual smoke test of the affected feature, if applicable.
1. Single commit with the bump and the lockfile change.

The commit message names what changed and why: `chore(deps): bump stripe from 14.5.0 to 14.6.0 (CVE-2025-XXXX)`.

For automated dependency-monitoring (Dependabot, Renovate), the bot opens a PR with the manifest bump and the lockfile change. You review, run the verification gate, merge. The bot’s PR is a deliberate update, not an automatic install.

## Anti-patterns

**Pinning the manifest but not committing the lockfile.** The pinning is irrelevant if the lockfile isn’t in the repo. Always commit the lockfile.

**Pinning some dependencies and not others.** Either commit to the discipline or don’t. A manifest with `"next": "14.2.15"` next to `"react": "^18.0.0"` reads as careless. Pin everything.

**Bumping every package every week.** The pinning discipline doesn’t mean “never update”; it means “update deliberately.” Most projects don’t need to chase the latest minor release of every dependency. Update when there’s a reason: a security patch, a feature you need, a deprecation you’re addressing.

**Using `latest` or `*`.** Worse than ranges. The version installed depends on the day. Avoid in any project beyond a one-off script.

**Manifest with a comment explaining why a range exists.** “We use `^` here because we want patch updates automatically.” If you want patch updates automatically, run a scheduled bot job that opens PRs. Don’t bake the auto-update into the manifest.

## Negative consequences

- **Manual update work.** Without ranges, you don’t get the “automatic” minor/patch updates. For a small, slow-moving project this is fine. For a project that depends on dozens of packages with frequent security fixes, this is more friction than the conventional approach.
- **Lockfile is mandatory.** Some workflows that work fine without a lockfile (early-stage exploration, throwaway scripts) need to include one. Minor cost.
- **Bot-driven updates have to be reviewed.** Renovate / Dependabot PRs need a human to look at them. With ranges, you might just trust the install. The pinning approach forces review, which is good *and* a real time cost.
- **First-time setup is slower for contributors.** They can’t install whatever’s compatible; they install exactly what’s pinned. Almost never a real problem, but worth noting.

The trade-off is reproducibility against velocity. For most projects in the size range this handbook addresses (single developer, small team, deliberate change discipline), reproducibility wins.

## Verification

A simple convention guard catches drift:

```ts
import packageJson from '../package.json'

describe('dependency pinning', () => {
  it('all dependencies are pinned to exact versions', () => {
    const violations: string[] = []
    for (const [name, version] of Object.entries(packageJson.dependencies ?? {})) {
      if (typeof version === 'string' && /[\^~]/.test(version)) {
        violations.push(`${name}: ${version}`)
      }
    }
    for (const [name, version] of Object.entries(packageJson.devDependencies ?? {})) {
      if (typeof version === 'string' && /[\^~]/.test(version)) {
        violations.push(`${name}: ${version}`)
      }
    }
    expect(violations).toEqual([])
  })
})
```

Add to the test suite. CI fails on any prefixed version. The discipline is automated.

## Related

- `convention-guard-tests` — the general shape this verification is a case of.
- `process/four-step-verification-gate.md` (Session 2B) — the gate that runs after every dependency update.
