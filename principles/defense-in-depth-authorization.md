# Principle: Defense-in-depth authorization

No single authorization layer is enough. A request that mutates state must be authorized at every layer that can refuse it. Each layer catches a different class of mistake.

## The minimum layer count

For a typical web application with a database:

1. **Database-level authorization** (RLS in Postgres, fine-grained access control elsewhere). Catches: misconfigured server actions, ORM queries that bypass middleware, future changes that introduce new query paths.
1. **Server-side authorization** (explicit role checks in server actions / API handlers). Catches: misconfigured database policies, schema migrations that drop a policy, queries that run as a service role and need application-level gating.
1. **Route-level authorization** (middleware or layout guards). Catches: deep-linking to URLs the user shouldn’t see, navigation mistakes that would otherwise reach the action layer.

A request must pass all three. Each is fallible alone; the combination is robust.

## Why redundancy is not waste

The conventional argument against defense in depth is “that’s redundant — we already check it in X.” This argument fails because:

- The layers fail in different ways. A database policy can be dropped during a migration and the test suite might not catch it. A server action’s role check can be commented out during a refactor. A route guard can be added to the wrong layout.
- The cost of each layer is small. Adding a role check at the top of a server action is two lines.
- The cost of a missed layer is large. A single missing check on a single endpoint can leak data to the entire user base.

The non-redundant version of “defense in depth” is “we trust this one check.” That trust is misplaced often enough that the redundancy earns its keep.

## What this looks like in practice

A server action that updates a record might look like:

```ts
'use server'

import { getCurrentUser } from '@/lib/auth'
import { hasRole } from '@/lib/auth/roles'
import { updateRecord } from '@/lib/data/records'
import { revalidatePath } from 'next/cache'

export async function updateRecordAction(
  recordId: string,
  patch: RecordPatch
): Promise<ActionResult> {
  // Layer 2: server-side authorization
  const user = await getCurrentUser()
  if (!user) return { error: 'unauthenticated' }
  if (!hasRole(user, 'manager')) return { error: 'forbidden' }

  // Layer 1: the database call respects RLS automatically because
  // the data layer uses the user-bound Supabase client (not service role)
  const result = await updateRecord(recordId, patch)
  if (!result.ok) return { error: result.reason }

  revalidatePath(`/records/${recordId}`)
  return { success: true }
}
```

And the route group containing the page that calls this action:

```ts
// app/(manager)/layout.tsx — Layer 3: route-level authorization
import { redirect } from 'next/navigation'
import { getCurrentUser } from '@/lib/auth'
import { hasRole } from '@/lib/auth/roles'

export default async function ManagerLayout({ children }) {
  const user = await getCurrentUser()
  if (!user || !hasRole(user, 'manager')) redirect('/login')
  return <>{children}</>
}
```

And the database policy:

```sql
-- Layer 1: RLS policy
create policy "managers can update records"
  on records for update
  using (public.get_user_role() = 'manager')
  with check (public.get_user_role() = 'manager');
```

If any one of these is misconfigured, the other two refuse the request. If all three are misconfigured, the bug is severe — but you’d have had to fail at three independent levels.

## Anti-patterns

- **“The middleware handles it.”** Middleware doesn’t run for every code path. A direct API call from another server action bypasses it.
- **“RLS handles it.”** RLS doesn’t run when the data layer uses the service-role client. The service-role client is required for some flows (registration, webhooks, cron). Anything that uses it must be authorized at the application layer.
- **“We don’t need RLS, the actions check.”** Then you’ve made the action layer the only barrier, which means a single missing check is total compromise. RLS is the layer of last resort; not having it means the last resort is “hope the action layer is right.”
- **“The role check is in the data layer function.”** Wrong layer. Role checks at the action layer mean the same data layer function can be reused with different role requirements. Role checks at the data layer mean every caller must agree on the role rules.

## Where this is enforced

In the handbook’s [`patterns/web/rls-null-coalescence-guard.md`](../patterns/web/rls-null-coalescence-guard.md) and [`patterns/test-correctness/role-write-matrix-manifest.md`](../patterns/test-correctness/role-write-matrix-manifest.md), automated tests assert that:

- Every RLS policy’s `USING` and `WITH CHECK` clauses conform to a documented shape (catches the NULL-coalescence leak class).
- Every server action’s expected-role declaration matches the union of roles in the relevant RLS policies (catches drift between the action layer and the database layer).

The `[`role-write-matrix-manifest`]` test is what catches the class of mistake “I added a new role to the action but forgot to update the RLS policy.” Without that test, defense-in-depth degrades to defense-in-three-layers-where-one-is-stale.

## Negative consequences

- Three layers is more code than one layer. Reading any single endpoint is more work because you have to read all three.
- Adding a new role requires touching multiple files. If the test infrastructure doesn’t catch drift, the layers go out of sync.
- Layer 3 (route guards) sometimes fights with the framework. Next.js layouts have re-render gotchas; middleware has its own constraints. The layer is correct; the framework integration is occasionally awkward.

The mitigation for all of these is the role-write-matrix-manifest test. The mitigation for none of these is dropping a layer.
