# Case study 02: An N+1 query that the spy test caught before users did

**Category:** performance
**Patterns referenced:** `patterns/test-correctness/n-plus-1-spy-regression-guards.md`, `patterns/universal/pure-function-test-isolation.md`
**Severity:** Medium (page load time, no data correctness issue)
**Time to detect:** ~6 hours after the regression shipped to staging
**Time to fix once detected:** ~2 hours

## Context

A community-feed feature in a content application. The feed page renders posts with: author info (name, avatar), like count, top three comments, and a "is this user following the author?" indicator.

The feed query was straightforward. In the data layer:

```ts
// src/lib/feed/get-feed.ts
export async function getFeed(currentUserId: string): Promise<FeedPost[]> {
  const posts = await db.posts.findMany({
    where: { /* visibility filters */ },
    orderBy: { created_at: 'desc' },
    take: 50,
  })

  const enriched = await Promise.all(posts.map(async (post) => ({
    ...post,
    author: await getUser(post.author_id),
    likeCount: await countLikes(post.id),
    topComments: await getTopComments(post.id, 3),
    isFollowingAuthor: await checkFollowing(currentUserId, post.author_id),
  })))

  return enriched
}
```

The page rendered correctly. Pagination worked. Tests passed (each helper had its own unit tests). Reviewed and merged.

## The symptom

The feature shipped to staging on a Monday. Tuesday morning, a developer running smoke tests noticed the feed page load was slow — about 4 seconds for the first 50 posts. Production has substantially more posts than staging, so the team flagged it for investigation before promoting to production.

There were no errors. No exceptions. The page just took 4 seconds. Browser network panel showed a single request to `/api/feed` returning correct data after 3.8 seconds of server processing.

## The bug

The first investigative step was the N+1 spy test that the project had standardized. The existing test had been written for a different list-view endpoint:

```ts
// src/lib/feed/__tests__/get-feed.spec.ts
import { vi, expect, describe, it } from 'vitest'

describe('getFeed', () => {
  it('does not produce N+1 query patterns', async () => {
    const dbSpy = installDbSpy()
    const posts = makeMockPosts(50)
    await seedTestDb(posts)

    await getFeed('test-user-id')

    // The spy counts SELECT statements grouped by query shape.
    // Acceptable: a small constant number per shape, independent of post count.
    const queryStats = dbSpy.summary()
    expect(queryStats['select_users_by_id']).toBeLessThanOrEqual(2)
    expect(queryStats['select_likes_count_for_post']).toBeLessThanOrEqual(2)
    expect(queryStats['select_comments_for_post']).toBeLessThanOrEqual(2)
    expect(queryStats['select_follow_by_pair']).toBeLessThanOrEqual(2)
  })
})
```

The test had been written for an earlier version of the feed (which used a join). The new code wasn't connected to this test because it lived in `getFeed`, not in the older `getFeedV1` the test exercised. The developer who shipped the new code hadn't added a corresponding spy test for the new function.

Pointing the spy at the new function produced:

```
Query shape counts after getFeed():
  select_posts_recent:           1
  select_users_by_id:            50    <- N+1!
  select_likes_count_for_post:   50    <- N+1!
  select_comments_for_post:      50    <- N+1!
  select_follow_by_pair:         50    <- N+1!
```

Total: 201 queries for 50 posts. Round-trip-bound; no amount of query optimization on individual statements would help.

## Root cause

The code was textbook N+1. `Promise.all(posts.map(async (post) => ...))` looks parallel but it just means many concurrent round-trips. Each post fired four queries; 50 posts fired 200 dependent queries (plus the initial fetch).

Two contributing factors:

1. **The helpers (`getUser`, `countLikes`, etc.) were pure functions that fetched one item at a time.** They were correct in isolation; they had unit tests; they were used in many other places. Each one was fine.
1. **The composer (`getFeed`) didn't have an N+1 test.** It was a new function; the project's `n-plus-1-spy-regression-guards` pattern requires every list-returning function to have a spy test. The developer missed it.

## The fix

The fix had two parts: implement batched fetches, and add the spy test.

Batched fetches:

```ts
export async function getFeed(currentUserId: string): Promise<FeedPost[]> {
  const posts = await db.posts.findMany({
    where: { /* visibility filters */ },
    orderBy: { created_at: 'desc' },
    take: 50,
  })

  // Collect all the IDs we need to fetch
  const authorIds = [...new Set(posts.map(p => p.author_id))]
  const postIds = posts.map(p => p.id)

  // Issue ~4 batched queries instead of 200 sequential ones
  const [authors, likeCounts, topCommentsByPost, followings] = await Promise.all([
    getUsersByIds(authorIds),                              // 1 query
    countLikesForPosts(postIds),                           // 1 query, returns Map<postId, count>
    getTopCommentsForPosts(postIds, 3),                    // 1 query, returns Map<postId, Comment[]>
    getFollowingsBetween(currentUserId, authorIds),        // 1 query, returns Set<authorId>
  ])

  const authorsById = new Map(authors.map(a => [a.id, a]))

  return posts.map(post => ({
    ...post,
    author:           authorsById.get(post.author_id)!,
    likeCount:        likeCounts.get(post.id) ?? 0,
    topComments:      topCommentsByPost.get(post.id) ?? [],
    isFollowingAuthor: followings.has(post.author_id),
  }))
}
```

Total queries dropped from 201 to 5. Page load went from 3.8 seconds to ~150ms.

The spy test, now attached to `getFeed`:

```ts
describe('getFeed', () => {
  it('does not produce N+1 query patterns', async () => {
    const dbSpy = installDbSpy()
    const posts = makeMockPosts(50)
    await seedTestDb(posts)

    await getFeed('test-user-id')

    const queryStats = dbSpy.summary()
    // Each shape should appear at most twice (the implementation itself + one cache lookup)
    for (const shape of Object.keys(queryStats)) {
      expect(queryStats[shape]).toBeLessThanOrEqual(2)
    }
    // And the total should be small regardless of post count
    expect(dbSpy.totalQueryCount()).toBeLessThanOrEqual(8)
  })
})
```

The `.toBeLessThanOrEqual(8)` is calibrated to current behavior (5 queries) plus a small headroom for genuine future additions. If a future change pushes the count past 8, the test fails and the change must justify itself.

A deliberate-violation pass: revert one of the batched calls to its per-item form, confirm the test fails with a clear "shape X has 50 queries, max allowed 2" message, restore.

## What got better afterward

1. **The spy test became a convention.** Every new list-returning function in the data layer ships with an N+1 spy test alongside its unit tests. Code review enforces; convention guard test grep-checks for missing spies.
1. **The single-item helpers were complemented by batch helpers.** `getUser` (one) and `getUsersByIds` (many) coexist. Most callers use the batch form; single-item form remains for genuinely-one-at-a-time cases. Naming convention surfaces the difference.
1. **The page load budget became explicit.** "Feed page server-side processing must be under 500ms for typical input" was added to the performance budget docs. The spy test indirectly enforces by capping query count.

## Lessons

- **N+1 is invisible in correctness tests.** Every individual fetch returned correct data. Every composed result was the right shape. The bug is *the number of fetches*, which isn't observable from output alone.
- **The pattern that catches it must be applied to the new function, not just exist somewhere in the codebase.** A spy test on an old function doesn't protect a new function with similar shape. The discipline is "every list function gets a spy test" — applied at the time of writing.
- **Pure helpers that compose nicely produce N+1 when composed naively.** `getUser(id)` is correct in isolation; `posts.map(p => getUser(p.author_id))` is the bug. The composer is where the discipline matters.
- **The spy test's value isn't in the first run; it's in the regression case.** The test caught the bug in the staging deploy because someone *ran* the test. A test that's not run doesn't catch anything. The four-step verification gate (`process/four-step-verification-gate.md`) runs the test on every commit; that's what catches the regression next time someone forgets.
- **Two hours of fix work avoided a slow page in production.** Not a security incident; not a data corruption; just slow. But "slow page" is what causes users to bounce and revenue to drop. Performance bugs deserve the same discipline as correctness bugs.

## Related

- `patterns/test-correctness/n-plus-1-spy-regression-guards.md` — the pattern this case study is a worked example of.
- `patterns/universal/pure-function-test-isolation.md` — the testing approach that makes the spy possible.
- `patterns/test-correctness/proxy-on-mutation-target.md` — a different shape of "count what happens" testing, for mutations.
- `process/four-step-verification-gate.md` — the mechanism that ensures the spy actually runs.
