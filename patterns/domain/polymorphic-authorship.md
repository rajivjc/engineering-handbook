# Polymorphic authorship

**Category:** domain
**Applies to:** any application where multiple actor types (members, staff, admins, system, anonymous) can be the originator of the same kind of record.

## Problem

A social feed pattern: posts, comments, reactions. Every post has an author. The naive schema:

```sql
create table posts (
  id uuid primary key,
  author_user_id uuid not null references users(id),
  body text not null,
  created_at timestamptz default now()
);
```

This works while every author is a “user.” It breaks the moment you have:

- **Staff posts** (system-driven announcements signed by a staff role, not a specific person).
- **System posts** (automated digests; no human author).
- **Anonymous posts** (member-driven but display-anonymous).
- **Cross-tenant posts** (an admin from another organization).

Tacking these onto the existing schema invites:

- Nullable `author_user_id` (which actor is null? the system? a deleted user? data corruption?).
- A `posted_by_system` boolean flag that’s true when `author_user_id` is null.
- Mixed responsibility for “who can edit this post?” (sometimes a user, sometimes anyone with role X, sometimes nobody).

The schema becomes a thicket of nullable columns and side-channel flags. RLS policies, edit permissions, and display logic all branch on these.

## Mechanism

Two fields together identify the author: a *kind* (which actor type) and an *id* (a reference scoped to that kind).

```sql
create table posts (
  id uuid primary key default gen_random_uuid(),

  author_kind text not null check (author_kind in ('user', 'staff_role', 'system')),
  author_id text,            -- semantics depends on author_kind:
                             --   user       -> users.id (uuid as text)
                             --   staff_role -> 'manager', 'owner', etc.
                             --   system     -> null
  
  body text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz,

  -- Constraint: author_id must be present iff author_kind requires it
  constraint author_id_matches_kind check (
    (author_kind = 'user' and author_id is not null) or
    (author_kind = 'staff_role' and author_id is not null) or
    (author_kind = 'system' and author_id is null)
  )
);
```

Display logic:

```ts
type Author =
  | { kind: 'user'; userId: string; displayName: string; avatarUrl: string | null }
  | { kind: 'staff_role'; roleName: string; displayLabel: string }
  | { kind: 'system' }

async function resolveAuthor(post: Post): Promise<Author> {
  switch (post.author_kind) {
    case 'user': {
      const user = await getUserById(post.author_id!)
      return {
        kind: 'user',
        userId: user.id,
        displayName: user.full_name,
        avatarUrl: user.avatar_url,
      }
    }
    case 'staff_role': {
      // 'manager' -> 'The Management', 'owner' -> 'Ownership Team'
      return {
        kind: 'staff_role',
        roleName: post.author_id!,
        displayLabel: STAFF_ROLE_DISPLAY_NAMES[post.author_id!] ?? post.author_id!,
      }
    }
    case 'system': {
      return { kind: 'system' }
    }
  }
}
```

Edit-permission logic:

```ts
function canEdit(post: Post, currentUser: User | null): boolean {
  if (currentUser === null) return false

  switch (post.author_kind) {
    case 'user':
      // Original author can edit; staff can edit anything
      return post.author_id === currentUser.id || hasRole(currentUser, 'staff')
    case 'staff_role':
      // Anyone with that staff role can edit
      return hasRole(currentUser, post.author_id!)
    case 'system':
      // System posts are immutable
      return false
  }
}
```

Each branch is explicit. No nullable fields, no side-channel flags, no “if author_id is null AND posted_by_system is true.”

## Why a string discriminator and not multiple FK columns

You could model this with multiple nullable foreign keys:

```sql
create table posts (
  id uuid primary key,
  author_user_id uuid references users(id),
  author_staff_role text,
  -- ... and you check exactly one is non-null
);
```

This is wrong for two reasons:

1. **Adding a new author kind requires a schema change.** `author_anonymous_session_id`, `author_external_partner_id` — each needs a new column. The discriminator column scales with no schema change; just a new value.
2. **Constraints get harder to write.** “Exactly one of N nullable columns is non-null” is a check constraint that must be updated every time N changes. The kind-plus-id pattern uses a single check constraint per kind.

The string discriminator is the canonical pattern for this shape; it’s how `polymorphic_type` works in many ORMs and how event-sourced systems represent actor identity.

## Anti-patterns

**Using the discriminator without the constraint.** `author_kind = 'system'` with `author_id = 'some-user-id'` is a corrupted state that’s not caught by the schema. The check constraint enforces the relationship.

**Storing the user’s display name on the post.** Tempting for performance, but display names change. Storing them denormalizes; you have to update every post when a user renames. Use the resolver pattern at read time.

**Sharing the discriminator’s value space across kinds.** `author_id = 'manager'` for staff_role is fine; `author_id = 'manager'` for a user (who happened to be named “Manager”) is not. Make the value space deliberately separate — UUIDs for users, role enum values for staff, never overlap.

**Different RLS policies for each branch when one would do.** RLS policies often boil down to “the author can edit; staff can edit anything; admins can do anything.” The post’s `author_kind` and `author_id` plus the current user’s role suffice. Don’t write three policies — write one with branching logic.

**Letting the application invent author kinds at write time.** New author kinds should require a schema change to update the check constraint, not just an application-level decision. The constraint is the contract.

## Negative consequences

- **More joins / lookups at read time.** `resolveAuthor()` does a database lookup for user-kind posts, a hashtable lookup for staff-role posts. Mitigate with the standard caching strategies; for typical feed-render workloads the cost is fine.
- **The display layer has more cases.** A simple “show user name” pattern is now “show different things for different author kinds.” Mitigate with a renderer component that takes an `Author` and dispatches; render once per kind.
- **Schema check constraints can be slow on large tables.** Adding a new `author_kind` value requires an `ALTER TABLE` that may rewrite the table on some databases. Plan migrations carefully (or use a CHECK that uses a separate enum table for extensibility).
- **The discriminator must stay in sync with code expectations.** A new `'partner'` kind in the database without corresponding application code produces broken posts. The migration and the code change ship together.

## When to introduce this pattern

Day one if you know multiple actor kinds are coming. The cost upfront is small (one extra column, one check constraint, one resolver function). The cost of retrofitting is large (every existing post needs migration, every read path needs updating, every RLS policy needs revision).

If you genuinely have only one actor kind and have no plans for more, the simple FK is fine. The pattern earns its keep when you have *more than one* actor kind.

## Verification

```ts
describe('polymorphic authorship', () => {
  it('rejects posts where the kind/id pair violates the constraint', async () => {
    await expect(
      db.posts.insert({ author_kind: 'system', author_id: 'something', body: 'x' })
    ).rejects.toThrow(/author_id_matches_kind/)
    
    await expect(
      db.posts.insert({ author_kind: 'user', author_id: null, body: 'x' })
    ).rejects.toThrow(/author_id_matches_kind/)
  })

  it('resolveAuthor returns the right shape for each kind', async () => {
    const userPost = await createUserPost(userA)
    const staffPost = await createStaffPost('manager')
    const systemPost = await createSystemPost()

    expect((await resolveAuthor(userPost)).kind).toBe('user')
    expect((await resolveAuthor(staffPost)).kind).toBe('staff_role')
    expect((await resolveAuthor(systemPost)).kind).toBe('system')
  })

  it('canEdit applies the right rule per kind', () => {
    const userPost = { author_kind: 'user', author_id: userA.id, ...rest }
    expect(canEdit(userPost, userA)).toBe(true)
    expect(canEdit(userPost, userB)).toBe(false)
    expect(canEdit(userPost, staffMember)).toBe(true)

    const staffPost = { author_kind: 'staff_role', author_id: 'manager', ...rest }
    expect(canEdit(staffPost, userA)).toBe(false)
    expect(canEdit(staffPost, manager)).toBe(true)
    expect(canEdit(staffPost, owner)).toBe(false)  // unless owner has manager role too

    const systemPost = { author_kind: 'system', author_id: null, ...rest }
    expect(canEdit(systemPost, owner)).toBe(false)  // system posts are immutable
  })
})
```

The constraint test is load-bearing — it verifies the database refuses to accept corrupted states.

## Related

- `principles/defense-in-depth-authorization.md` — the constraint is one layer; the application’s `canEdit` check is another.
- `patterns/web/rls-null-coalescence-guard.md` — when writing RLS policies for polymorphic tables, the null-coalescence concerns multiply (the user might not have a role; the post’s author kind might be unfamiliar).
- `patterns/universal/single-source-of-truth-transformer.md` — `resolveAuthor` is a transformer that all surfaces consume.
