# Unimplemented config error pattern

**Category:** domain
**Applies to:** any application with configurable behavior where the configuration space is large and the implementation will arrive in stages.

## Problem

A league management module supports many possible configurations: round-robin or double-round-robin, win/draw/loss point values (3-1-0 standard or 2-1-0 traditional), tiebreakers (head-to-head, goal difference, points scored), promotion/relegation, multi-team galas, handicaps. Day-one shipping every combination is unrealistic.

Two anti-patterns appear when scope is forced into the first ship:

1. **Hardcode the one supported config.** “We’ll only do single round-robin with 3-1-0 scoring.” Six months later, a customer asks for double round-robin. Now you’re refactoring the league engine while the customer waits.
1. **Build the entire abstraction with stub implementations.** Every code path checks 47 config values; most return placeholder behavior; tests cover the path you actually use; the rest is dead code that pretends to work.

The middle ground: model the *full* configuration space in the schema and types, but explicitly reject configurations the engine doesn’t yet support. New configurations are unlocked one at a time, each with a deliberate decision and a real implementation.

## Mechanism

### A configuration type that’s complete in shape but bounded in supported values

```ts
// src/competitions/leagues/config.ts

export interface LeagueConfig {
  format: 'single_round_robin' | 'double_round_robin'
  scoring: { win: number; draw: number; loss: number }
  tiebreaker: 'head_to_head' | 'goal_difference' | 'points_scored'
  promotionRelegation: {
    enabled: boolean
    promotedCount: number
    relegatedCount: number
  }
  multiTeamGalas: { enabled: boolean }
  handicap: { enabled: boolean; method: 'manual_race_to' | 'skill_level_display' }
  rosterEnforcement: 'strict' | 'flexible'
}

export class LeagueConfigNotImplementedError extends Error {
  constructor(public readonly config: LeagueConfig, public readonly reason: string) {
    super(`League configuration not yet implemented: ${reason}`)
    this.name = 'LeagueConfigNotImplementedError'
  }
}

const SUPPORTED_CONFIGS: Array<{ name: string; matches: (c: LeagueConfig) => boolean }> = [
  {
    name: 'foundation: single round-robin, 3-1-0, no promotion, strict roster',
    matches: (c) =>
      c.format === 'single_round_robin' &&
      c.scoring.win === 3 && c.scoring.draw === 1 && c.scoring.loss === 0 &&
      c.tiebreaker === 'head_to_head' &&
      !c.promotionRelegation.enabled &&
      !c.multiTeamGalas.enabled &&
      !c.handicap.enabled &&
      c.rosterEnforcement === 'strict',
  },
  // Future entries added one at a time as configurations are implemented
]

export function assertConfigSupported(config: LeagueConfig): void {
  const supported = SUPPORTED_CONFIGS.find(s => s.matches(config))
  if (supported) return

  // Diagnose which fields are out-of-band
  const reasons: string[] = []
  if (config.format !== 'single_round_robin') reasons.push(`format='${config.format}'`)
  if (config.scoring.win !== 3 || config.scoring.draw !== 1 || config.scoring.loss !== 0) {
    reasons.push(`scoring=${JSON.stringify(config.scoring)}`)
  }
  if (config.promotionRelegation.enabled) reasons.push('promotionRelegation enabled')
  if (config.multiTeamGalas.enabled) reasons.push('multiTeamGalas enabled')
  if (config.handicap.enabled) reasons.push('handicap enabled')
  if (config.rosterEnforcement !== 'strict') reasons.push(`rosterEnforcement='${config.rosterEnforcement}'`)

  throw new LeagueConfigNotImplementedError(
    config,
    reasons.length ? reasons.join(', ') : 'unknown variation'
  )
}
```

### Explicit assertion at every entry point

Every function that operates on a league configuration calls `assertConfigSupported` before doing real work:

```ts
export function generateFixtures(config: LeagueConfig, teams: Team[]): Fixture[] {
  assertConfigSupported(config)
  // ... implementation that ASSUMES single_round_robin
}

export function computeStandings(config: LeagueConfig, fixtures: Fixture[]): Standings {
  assertConfigSupported(config)
  // ... implementation that ASSUMES 3-1-0 scoring with head-to-head tiebreak
}
```

If the database has a league row whose config is unsupported, the engine throws clearly instead of silently misbehaving. The error message tells the caller *what* about the configuration is unsupported.

### Surfacing the error to the user

```ts
// In a server action or page:
try {
  const fixtures = generateFixtures(league.config, teams)
  return { success: true, fixtures }
} catch (err) {
  if (err instanceof LeagueConfigNotImplementedError) {
    return {
      success: false,
      error: 'unsupported_config',
      reason: err.reason,
      message: `This league uses a configuration that's not yet implemented (${err.reason}). ` +
               `Supported configurations are listed in the docs.`,
    }
  }
  throw err
}
```

A user trying to use an unimplemented configuration sees a specific error, not a crash. The product team has a clear data point: “N users hit this error this week” tells you which configuration to implement next.

## Why a typed error class

A plain `throw new Error('not implemented')` is hard to handle:

- The caller can’t distinguish “config not implemented” from any other error.
- The error message is the only carrier of “what’s unsupported” — no structured data.
- Catching it requires string-matching the message, which is fragile.

The typed `LeagueConfigNotImplementedError` carries the offending config as data. Callers can branch cleanly:

```ts
catch (err) {
  if (err instanceof LeagueConfigNotImplementedError) {
    // structured data is on err.config and err.reason
  }
}
```

For typed-language ecosystems (TypeScript, Java, Rust), this pattern is mandatory. For dynamic languages, use a sentinel string in the error and check against it.

## When to add a new supported configuration

The discipline is “one supported configuration per session.” Adding double-round-robin:

1. The session’s spec names the new combination explicitly.
1. The implementation handles the new path everywhere — fixtures generator, standings computer, schedule renderer, etc.
1. Tests cover the new combination’s behavior end to end.
1. A new entry is added to `SUPPORTED_CONFIGS` matching exactly the new combination.
1. The deliberate-violation pass: try a configuration *just past* the new one (e.g., double-round-robin + handicap if handicap is still unsupported); confirm the error fires.

The audit checks: every entry in `SUPPORTED_CONFIGS` has a matching test that exercises that configuration to completion.

## Anti-patterns

**Silent fallback to a default configuration.** “If unsupported, treat it as single round-robin.” Now the user thinks their double-round-robin league is running; it’s actually a single round-robin with hidden behavior. The error pattern fails *loud* — the user sees a clear error and knows to wait for the feature.

**TODO comments in place of the assertion.** “TODO: handle double-round-robin.” When the user creates a double-round-robin league, the engine runs anyway and produces wrong results. The assertion at the entry point is the structural enforcement; comments are aspirational.

**A single boolean per config field that’s checked deep in the engine.** “If `config.handicap.enabled`, branch here.” Fifty branches throughout the codebase. When you forget one, the engine produces wrong output silently. The assertion *at the boundary* prevents the rest of the engine from running on unsupported input.

**Allowing the database to store unsupported configs without UI guard.** A league created via SQL or admin tool with an unsupported config slips past the form. The engine catches it (because of the assertion), but the user only finds out when they try to view fixtures. Mitigate: validate at create time too, not just at run time.

**Treating “not implemented” as a permanent state.** Each unsupported configuration should be on a roadmap. If a configuration has been “not implemented” for two years, either implement it or remove it from the type entirely.

## Negative consequences

- **More verbose than just hardcoding the supported case.** A “we only support single round-robin” branch in five places becomes one assertion in fifty places. Mitigated by extracting the assertion to one function called from the entry points.
- **Adding a new configuration is a real session.** “Just enabling double-round-robin” might mean fixtures, standings, scheduler, UI, and admin all need updates. The pattern surfaces this; the alternative (silent fallback) hides it until users complain.
- **The supported-configs list ages.** When you’ve added 12 configurations, the matchers get verbose. Refactor periodically; group related configs.
- **Tests must explicitly cover *each* supported configuration.** Otherwise an entry in the list isn’t actually verified.

## Verification

```ts
describe('assertConfigSupported', () => {
  const baseConfig: LeagueConfig = {
    format: 'single_round_robin',
    scoring: { win: 3, draw: 1, loss: 0 },
    tiebreaker: 'head_to_head',
    promotionRelegation: { enabled: false, promotedCount: 0, relegatedCount: 0 },
    multiTeamGalas: { enabled: false },
    handicap: { enabled: false, method: 'manual_race_to' },
    rosterEnforcement: 'strict',
  }

  it('accepts the foundation configuration', () => {
    expect(() => assertConfigSupported(baseConfig)).not.toThrow()
  })

  it('rejects configurations with double round-robin', () => {
    const c = { ...baseConfig, format: 'double_round_robin' as const }
    expect(() => assertConfigSupported(c)).toThrow(LeagueConfigNotImplementedError)
    expect(() => assertConfigSupported(c)).toThrow(/format='double_round_robin'/)
  })

  it('rejects configurations with promotion/relegation', () => {
    const c = { ...baseConfig, promotionRelegation: { enabled: true, promotedCount: 1, relegatedCount: 1 } }
    expect(() => assertConfigSupported(c)).toThrow(/promotionRelegation enabled/)
  })

  it('error reason names every offending field', () => {
    const c = {
      ...baseConfig,
      format: 'double_round_robin' as const,
      handicap: { enabled: true, method: 'manual_race_to' as const },
    }
    try {
      assertConfigSupported(c)
    } catch (err) {
      if (err instanceof LeagueConfigNotImplementedError) {
        expect(err.reason).toMatch(/format/)
        expect(err.reason).toMatch(/handicap/)
      }
    }
  })
})
```

The fourth test is load-bearing — it ensures the error message lists every reason, not just the first one detected. Multi-field unsupported configs need this for users to understand what to change.

## Related

- `principles/atomic-state.md` — same philosophy: prefer explicit failure to silent partial behavior.
- `patterns/test-correctness/deliberate-violation-verification.md` — the assertion is verified by deliberately writing tests that pass an unsupported config and confirming the error fires.
- `patterns/domain/single-elimination-bracket-with-lazy-rounds.md` — sibling pattern; the bracket implementation uses the same “configurable in shape, restricted in supported values” stance for tournament formats.
