# Migration ordering discipline

**Category:** process
**Applies to:** any project with a sequence of database schema migrations applied in filename or numeric order, especially Postgres-based projects with helper functions and triggers alongside DDL.

## Problem

A migration file `0009_create_helpers.sql` defines a Postgres function:

```sql
create or replace function public.refund_booking(p_booking_id uuid)
returns void
language plpgsql
as $$
begin
  insert into credit_ledger (user_id, amount, source_id, ...)
  select user_id, -credits_used, id, ...
  from bookings where id = p_booking_id;
  ...
end;
$$;
```

The function compiles. The migration applies cleanly to the local database — *because* the local database already has `bookings` and `credit_ledger` from earlier migrations.

A new developer clones the repo, creates a fresh database, runs `supabase migration up` (or your equivalent migration runner). At migration `0009`, the runner errors:

```
ERROR: relation "credit_ledger" does not exist
```

The function references `credit_ledger`, which is created in `0012_create_ledger.sql`. The migrations were applied to the original developer’s database in a particular order that happened to work; on a fresh database, the same files in numeric order fail.

The bug shipped because:

- Each migration was tested locally where the database state already matched expectations.
- CI ran tests against the same local-style state, not from a fresh database.
- Production was live; the production database had been built up over many sessions and never re-derived from scratch.

The fix is discipline: every schema change is ordered with respect to its dependencies, and the full migration set is regularly verified against a fresh database.

## Mechanism

### Numbered prefix discipline

Use a strict ordering convention. Common shapes:

- **Sequential integers:** `0001_create_users.sql`, `0002_create_sessions.sql`, …
- **Timestamps:** `20260510120000_create_users.sql`, `20260510130000_create_sessions.sql`
- **Date-then-counter:** `2026-05-10_001_create_users.sql`, `2026-05-10_002_create_sessions.sql`

Pick one and never deviate. The runner applies in lexical order; a sequence with gaps or out-of-order numbers loses determinism.

### The dependency rule

A migration may only reference objects (tables, types, functions, sequences) that exist *after a strictly earlier migration has applied*. To verify mentally:

> “If I throw away my database and run only migrations 1 through N, will migration N apply cleanly?”

If the answer is “no” for any N, the ordering is wrong.

This rule is recursive. A function in migration 7 that references a table created in migration 4 is fine. A function in migration 4 that references a table created in migration 7 is broken — even if both are in `create or replace function` form, the reference is resolved on call, but most migration runners compile the function during apply, surfacing the missing relation.

### Splitting into earlier and later migrations

When a function genuinely needs to reference tables that come later in the natural design order, split:

- `0007_create_helper_function_signature.sql` — defines a function with a stub body that doesn’t reference the late table.
- `0012_create_ledger.sql` — creates the ledger table.
- `0013_finalize_helper_function.sql` — `create or replace function` updates the function with the real body that references the now-existing table.

Or simpler: move the helper function to *after* the table it depends on. Most projects choose this; the only reason to keep the function early is if it’s referenced by migrations 8–11 (in which case those migrations also need re-ordering).

### Reading the migration list as a dependency graph

Periodically (e.g., before each release), read the migration list as if it were a topological sort. For each migration, ask:

- What objects does this migration *create*?
- What objects does this migration *reference*?
- Are all referenced objects created in a strictly earlier migration?

For complex schemas, this is tedious by hand. Tools help: `pg_dump` of a fresh-DB-built database, then comparing the result to a `pg_dump` of the production database. Differences indicate ordering issues.

## The fresh-database verification

The single most important test: from a totally empty database, run all migrations in order. They must all succeed.

```bash
# scripts/verify-migrations-from-scratch.sh
#!/usr/bin/env bash
set -euo pipefail

# Drop and recreate the local database
psql -c 'drop database if exists app_test;'
psql -c 'create database app_test;'

# Run all migrations in order against the fresh DB
DATABASE_URL=postgres://...app_test supabase migration up

# Compare schema to a known-good reference
psql app_test -c '\dt'  # all tables present
psql app_test -c '\df+' # all functions present and compile

# Run a smoke test seed
psql app_test -f scripts/test-seed.sql

echo "Fresh-DB migration test: PASSED"
```

Run this in CI. Run it locally before every push that touches migrations. The test is the load-bearing check; lexical inspection of the migration order is supplementary.

## Why CI is necessary

The local development database is rarely fresh. The developer adds migration after migration, each one applying to the already-built state. The bug — a migration that references something created later — only appears when the migrations are applied to an empty database.

Without CI’s fresh-DB test, the bug ships. The first time someone builds a fresh production replica (a staging environment, a disaster recovery exercise, an onboarding machine) is the first time it fails. By then it’s harder to fix because production has data.

## Anti-patterns

**Editing already-applied migrations.** Once a migration has been applied to any environment (local, staging, production), it’s frozen. Edits don’t propagate; the original state is in the migration log. The fix is always a *new* migration, never an edit.

**Renaming migration files.** A file renamed from `0007_add_indexes.sql` to `0007a_add_indexes.sql` confuses the runner; it might re-apply, might skip, might error. Don’t rename. If you need to insert a migration earlier than 0008, either renumber going forward (painful) or accept a non-strictly-numeric inserted number (`0007_5_add_thing.sql` if your runner supports it; usually it doesn’t).

**Helpers in early migrations referencing late tables.** The bug at the top. Always order: tables first, then indexes, then functions/views/triggers that reference them.

**Migrations that depend on data being present.** A migration that says `update users set role = 'member' where role is null` assumes there are users. On a fresh DB, the table exists but is empty; the update affects zero rows; the migration silently completes. If the migration was meant to be a check (“there should be no null roles”), make it an assertion: `do $$ begin if exists (select 1 from users where role is null) then raise exception 'null roles found'; end if; end $$;`.

**Migrations that work locally because of execution-order accidents.** A migration that creates a function, then creates a table referenced by the function — works, because Postgres compiles function bodies lazily. Then on a fresh DB someone runs `select my_function(...)` before any subsequent migration; the function fails to resolve the table. Move table creation before the function.

**No test seed in CI.** The fresh-DB test confirms migrations *apply*. It doesn’t confirm they apply *to a usable schema*. A test seed that inserts representative rows and runs key queries catches additional issues (missing indexes causing timeouts, foreign-key constraints excluding valid data).

**Running migrations in production manually.** Production migrations should be CI-driven. A developer who runs migrations manually in production and then forgets to commit the migration file leaves production in a state nobody else can reproduce.

## Negative consequences

- **The fresh-DB test is slow.** Dropping and recreating the database, then applying many migrations, can take 30–60 seconds. Run it on every push to migration files; cache when possible.
- **Re-ordering a long migration history is hard.** Once you have 50 migrations and discover ordering issues, untangling is real work. Catch the issues early; if the project is small, audit the order during every migration session.
- **Some helper functions naturally want to be early.** Common utility functions (audit triggers, user-derivation functions) are referenced by many tables. They have to come after the tables they reference, even if they feel “more fundamental.”
- **The discipline doesn’t help against logical errors.** A migration that orders correctly but creates a wrong-shaped table is a different problem; ordering doesn’t catch it. Test seeds and integration tests catch logical errors.

## Verification

Three layers:

```bash
# 1. Lexical inspection: are filenames in strict order, no gaps, no renamings?
ls supabase/migrations/ | sort -c  # exits zero if already sorted

# 2. Fresh-DB apply: do all migrations apply in order against an empty DB?
./scripts/verify-migrations-from-scratch.sh

# 3. Test-seed apply: does the resulting schema accept representative data?
psql -d app_test -f scripts/test-seed.sql
```

For ongoing discipline:

- Every PR that adds or modifies migrations must show the fresh-DB test in CI green.
- Quarterly: run a “rebuild from scratch” exercise — a staging environment built from the current main branch. Confirms not just CI but the deployable artifact.

## Related

- `patterns/web/atomic-state-via-rpc.md` — the RPCs typically defined in migrations; ordering matters for the helper-references-table case.
- `principles/mock-real-parity.md` — fresh-DB-from-scratch is the “real” side; mock setup must match.
- `process/four-step-verification-gate.md` — fresh-DB verification is a separate gate, often run in CI alongside the four-step gate.
- `decisions/examples/mock-mode-required-day-one.md` (Session 1) — adjacent decision: mock mode bypasses the migration runner; ordering discipline applies only to the real path.
