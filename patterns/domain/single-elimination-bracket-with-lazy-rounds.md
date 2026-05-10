# Single-elimination bracket with lazy rounds

**Category:** domain
**Applies to:** any tournament-style application (sports leagues, gaming competitions, debate tournaments, eSports) that needs single-elimination brackets.

## Problem

The naive way to model a single-elimination tournament:

```sql
create table matches (
  id uuid primary key,
  tournament_id uuid not null,
  round_number integer not null,
  position_in_round integer not null,
  player_a_id uuid,
  player_b_id uuid,
  winner_id uuid,
  scheduled_at timestamptz
);
```

At tournament creation, you generate every match for every round up front. With 16 players, that’s 8 + 4 + 2 + 1 = 15 matches. Most of them have null `player_a_id` and `player_b_id` because the players who’ll play them don’t exist yet — they’re the winners of earlier rounds.

This is wrong for several practical reasons:

- **Validation is hard.** “A match must have two players” is universally true *except* for matches whose players haven’t been determined yet. The constraint “player IDs are nullable for future-round matches” is a runtime rule, not a schema rule.
- **Walkovers are awkward.** A player drops out before their match. You need to advance the opponent. With pre-generated matches, you have to mutate the next round’s match to fill in the player; the future-round match might already exist with placeholder data.
- **Re-seeding is impossible.** A manager wants to manually advance someone (an emergency rule). The next match has wrong placeholders. You’re editing the placeholder fields, which were never validated meaningfully.
- **Bye handling is special-cased.** With 13 players, three byes are needed. Pre-generated matches mean you have placeholder “bye” matches that look real but aren’t.

The fix: generate only the *first* round at tournament start. Subsequent rounds are created lazily, when the previous round’s matches have winners.

## Mechanism

### Schema

```sql
create table tournament_matches (
  id uuid primary key default gen_random_uuid(),
  tournament_id uuid not null references tournaments(id),
  round_number integer not null,        -- 1 for first round, 2 for next, etc.
  bracket_position integer not null,    -- 1, 2, 3, ... within the round
  
  player_a_id uuid not null references players(id),
  player_b_id uuid references players(id),  -- nullable for byes only

  winner_id uuid references players(id),
  -- if winner_id is null, match hasn't been played
  -- if winner_id = player_a_id or player_b_id, match has been played

  outcome_kind text,
  -- 'win', 'walkover_a', 'walkover_b', 'manager_override'

  played_at timestamptz,
  created_at timestamptz default now(),

  unique (tournament_id, round_number, bracket_position),
  
  check (
    (winner_id is null and outcome_kind is null) or
    (winner_id is not null and outcome_kind is not null)
  )
);
```

Notice: `player_a_id` is required, `player_b_id` is required *unless* it’s a bye. Future-round matches don’t exist yet, so this constraint always holds.

### Round generation

The first round is generated at tournament start. Byes are placed at known positions in the bracket (typically the top of the bracket gets byes when the player count isn’t a power of 2).

```ts
// src/competitions/data/bracket.ts
import 'server-only'

export interface Player { id: string; seedRank: number }
export interface FirstRoundMatch {
  bracket_position: number
  player_a_id: string
  player_b_id: string | null  // null = bye
}

export function generateFirstRound(players: Player[]): FirstRoundMatch[] {
  // Sort by seed rank ascending (rank 1 is top seed)
  const seeded = [...players].sort((a, b) => a.seedRank - b.seedRank)
  const playerCount = seeded.length

  // Bracket size is the next power of 2
  const bracketSize = nextPowerOfTwo(playerCount)
  const byeCount = bracketSize - playerCount

  // Standard seeding: top seeds get byes (or are paired with byes); seed pairs are 1 vs N, 2 vs N-1, etc.
  const matches: FirstRoundMatch[] = []
  for (let pos = 0; pos < bracketSize / 2; pos++) {
    const seedA = pos
    const seedB = bracketSize - 1 - pos

    const playerA = seeded[seedA]
    const playerB = seedB < playerCount ? seeded[seedB] : null  // null = bye

    matches.push({
      bracket_position: pos + 1,
      player_a_id: playerA.id,
      player_b_id: playerB?.id ?? null,
    })
  }
  return matches
}

function nextPowerOfTwo(n: number): number {
  let p = 1
  while (p < n) p *= 2
  return p
}
```

### Auto-advance via trigger or RPC

When a match completes (winner is set), the system creates the *next round’s match* if both feeder matches have winners.

```sql
create or replace function public.advance_after_match_complete(
  p_match_id uuid
)
returns table(ok boolean, next_match_id uuid)
language plpgsql
security invoker
as $$
declare
  v_match record;
  v_paired_match record;
  v_next_round_position integer;
  v_next_match_id uuid;
begin
  select * into v_match from tournament_matches where id = p_match_id;
  if v_match is null then
    return query select false, null::uuid;
    return;
  end if;
  if v_match.winner_id is null then
    return query select false, null::uuid;
    return;
  end if;

  -- The next round's bracket position is ceil(this_position / 2)
  v_next_round_position := (v_match.bracket_position + 1) / 2;

  -- Find the paired match (the other one feeding into the same next-round slot)
  select * into v_paired_match
    from tournament_matches
    where tournament_id = v_match.tournament_id
      and round_number = v_match.round_number
      and bracket_position in (v_match.bracket_position - 1, v_match.bracket_position + 1)
      and (v_match.bracket_position + 1) / 2 = v_next_round_position
    limit 1;

  -- If the pair hasn't completed, we don't create the next-round match yet
  if v_paired_match is not null and v_paired_match.winner_id is null then
    return query select true, null::uuid;
    return;
  end if;

  -- Both feeder matches have winners (or there's no pair, e.g., a bye-fed slot).
  -- Create the next-round match.
  insert into tournament_matches (
    tournament_id, round_number, bracket_position, player_a_id, player_b_id
  ) values (
    v_match.tournament_id,
    v_match.round_number + 1,
    v_next_round_position,
    v_match.winner_id,
    v_paired_match.winner_id  -- null only if the slot is the paired side of a bye
  ) returning id into v_next_match_id;

  return query select true, v_next_match_id;
end;
$$;
```

Now match completion triggers next-round creation, naturally and lazily. A walkover is just `winner_id := opponent_id, outcome_kind := 'walkover_a'` followed by the same advancement logic.

## Walkover and manager override

Walkovers fit naturally:

```sql
update tournament_matches
  set winner_id = player_b_id,
      outcome_kind = 'walkover_a',
      played_at = now()
  where id = $1;
-- Trigger or follow-up call: advance_after_match_complete($1)
```

Manager override (rare but needed) is the same shape:

```sql
update tournament_matches
  set winner_id = $newWinnerId,
      outcome_kind = 'manager_override',
      played_at = now()
  where id = $1;
```

If the overridden match’s *next-round match* already exists (because the previous winner had advanced), the override needs to cascade: revert the next round’s match (delete it or update its players) and re-derive. This is the trickiest case; the schema makes it tractable because the next-round match was created from the previous winners — change the winner, recompute the next round.

```sql
create or replace function public.revert_after_match_override(
  p_match_id uuid
)
returns void
language plpgsql
security invoker
as $$
declare
  v_match record;
  v_next_match record;
begin
  select * into v_match from tournament_matches where id = p_match_id;

  -- Find a next-round match this one fed into
  select * into v_next_match
    from tournament_matches
    where tournament_id = v_match.tournament_id
      and round_number = v_match.round_number + 1
      and bracket_position = (v_match.bracket_position + 1) / 2;

  if v_next_match is null then
    return;  -- no next round match; nothing to revert
  end if;

  -- If the next match was already played, recursively revert its consequences too
  if v_next_match.winner_id is not null then
    perform public.revert_after_match_override(v_next_match.id);
  end if;

  delete from tournament_matches where id = v_next_match.id;
end;
$$;
```

The recursion is bounded by the bracket depth (log₂ of player count). Override → revert next → revert next’s next → … → done. The application then calls `advance_after_match_complete` on the originally overridden match to regenerate the cascade with the correct winner.

## Anti-patterns

**Generating all rounds upfront with placeholder data.** The placeholders aren’t real and have to be ignored everywhere. Walkover and override logic becomes a tangle of “is this a real player or a placeholder?” checks.

**Treating byes as matches.** A player with a bye should advance directly to round 2 without a “match.” Modeling the bye as a match (player vs. nobody) clutters the schema with non-events.

**Recomputing the bracket on every read.** Tempting to derive matches from a “tournament participants” list at query time. But the matches need to record results (winner, played-at, walkover-or-real). Persistence is necessary.

**Foreign-key cascades on player deletion.** A player who quits mid-tournament shouldn’t `DELETE` their `tournament_matches` rows. Either the player record stays (recommended; mark them inactive) or the matches need explicit handling for the deletion case.

**Mixing tournament types in one table.** Single-elimination has different needs from round-robin or double-elimination. Don’t try to model all three with one table; the constraints diverge. See `unimplemented-config-error-pattern` for the “one table per format” approach with a clear extension story.

**Allowing matches to be edited freely.** Once a winner is set and the next round has been created, editing the previous match without cascading is a bug-creator. Wrap edits in the override+cascade flow even when the manager is “just fixing a typo.”

## Negative consequences

- **More moving parts than upfront generation.** The lazy creation, the override cascade, the walkover handling — each is straightforward; together they’re not trivial. Spec carefully and test extensively.
- **The bracket can’t be displayed in full until matches are created.** A user wants to see “the whole bracket” before the first round is played. You’ll need to *render* the future structure (computed) without *persisting* it.
- **Recursive override-cascade is database-side recursion.** Bounded by tournament depth, but worth noting; some Postgres deployments restrict recursive function calls. Test against your actual deployment.
- **Migration of an existing pre-generated bracket schema is real work.** This pattern is best chosen at design time; retrofit is expensive.

## Verification

For first-round generation:

1. 16 players → 8 matches, no byes.
1. 13 players → 8 matches, 3 of which are byes (bracket_position 1, 2, 3 by convention).
1. Byes correctly placed for top seeds.

For auto-advance:

1. Both feeder matches complete → next-round match created with both winners.
1. Only one feeder complete → no next-round match yet.
1. Bye advances directly: a bye match’s winner triggers advance even with no opponent.

For override:

1. Override a played match → cascade reverts next round, no zombie data.
1. Override a played match whose next round was also played → recursive cascade works.
1. Override an unplayed match → no cascade needed (no next round exists).

The cascade tests are the highest-risk; they’re the ones most likely to leave the database in an inconsistent state if the recursion is buggy.

## Related

- `patterns/domain/unimplemented-config-error-pattern.md` — for handling tournament formats not yet implemented.
- `patterns/web/atomic-state-via-rpc.md` — match completion + advancement should be a single transaction.
- `patterns/universal/module-boundary-tests-with-grep.md` — competition module benefits from boundary discipline; this pattern is module-internal.
