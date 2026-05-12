# Server-only import boundary

**Category:** web (Next.js App Router; generalizes to any framework with server/client component separation)
**Applies to:** code that uses server-side secrets, service-role database clients, or any capability that must never reach the browser bundle.

## Problem

In Next.js’s App Router, server components and client components share an import graph. A server component can import from `lib/data/`; a client component can also import from `lib/data/`. If `lib/data/` happens to use a server-only library (a service-role database client, a secret-bearing API client, a privileged file-system reader), the client component now bundles that code — including the secrets — into the browser bundle.

This is not a hypothetical. In a typical Next.js project:

- A data-layer function `getRecord(id)` uses the service-role Supabase client (because it needs to bypass RLS for some legitimate reason).
- A server component calls `getRecord(id)` in its render.
- A client component for an unrelated feature imports a *different* function from the same `lib/data/records.ts` file.
- The Next.js bundler now includes the *whole module* in the client bundle, including the service-role key reference.
- The key isn’t actually exposed (the bundler may tree-shake or replace `process.env.SUPABASE_SERVICE_ROLE_KEY` with `undefined` in client mode), but the *code path* is now in the browser, and any future change might leak the actual secret.

The conventional defense is “be careful.” The actual defense is the `server-only` package combined with a convention guard test.

## Mechanism

### The `server-only` import

Next.js ships a magic module called `server-only`. Importing it at the top of a file marks that file as server-only:

```ts
// src/lib/data/records.ts
import 'server-only'

import { createServiceRoleClient } from '@/lib/supabase/admin'

export async function getRecordPrivileged(id: string) {
  const supabase = createServiceRoleClient()
  // ... uses service role
}
```

If a client component (a file marked `'use client'`) imports this file (directly or transitively), Next.js fails the build with an error pointing at the import chain.

This is the load-bearing primitive. It catches the “client component imports server-only code” mistake at compile time.

### The convention guard

The `server-only` import is easy to forget when adding new files. A convention guard test enforces it for files in known-server-only directories:

```ts
// tests/conventions/server-only-imports.spec.ts
import { execSync } from 'node:child_process'
import path from 'node:path'

const SERVER_ONLY_DIRECTORIES = [
  'src/lib/data',
  'src/lib/supabase',
  'src/lib/auth',
  'src/lib/stripe',
  'src/lib/push',
  'src/competitions/data',
  'src/scheduling/data',
]

describe('server-only import discipline', () => {
  it('every file in server-only directories imports `server-only`', () => {
    const violations: string[] = []
    for (const dir of SERVER_ONLY_DIRECTORIES) {
      const cmd = `find ${dir} -type f -name '*.ts' -not -name '*.spec.ts' -not -name '*.test.ts' -not -name 'mock-data.ts'`
      const files = execSync(cmd, { encoding: 'utf-8' }).trim().split('\n').filter(Boolean)
      for (const file of files) {
        const content = require('fs').readFileSync(file, 'utf-8')
        if (!content.includes("import 'server-only'")) {
          violations.push(file)
        }
      }
    }

    if (violations.length === 0) return

    const message = [
      `Server-only directories with files missing the \`server-only\` import (${violations.length}):`,
      ...violations.map(v => `  ${v}`),
      '',
      'Add `import \\'server-only\\'` at the top of each file. This makes the bundler',
      'fail loudly if a client component ever imports from these files.',
    ].join('\n')
    throw new Error(message)
  })
})
```

The test fails if a contributor adds a new file under `src/lib/data/` (or any of the listed directories) without the `server-only` import. The fix is mechanical: add the import. The discipline is automated.

## Why both layers earn their keep

- **`server-only` catches the actual mistake.** A client component that accidentally imports a server-only module fails the build. This is the strict bundler-level defense.
- **The convention guard catches the *missing import***. Without it, a file in `src/lib/data/` *without* the `server-only` import is technically importable from a client component without the build failing — until the moment someone imports it. The guard ensures every file in known-server-only territory has the magic import, so the bundler’s defense is actually engaged.
- **Both are required.** The `server-only` import without the guard means new files might forget to add it. The guard without `server-only` means the test passes but nothing actually protects the bundle.

## What goes in server-only directories

- **Data layer.** Anything that talks to a database, especially with a service role.
- **Auth helpers.** Anything that handles cookies, sessions, JWTs server-side.
- **Secret-bearing API clients.** Stripe, push services, third-party APIs with private keys.
- **Cron and webhook handlers.** Code that runs on a schedule or in response to external events.
- **Server actions, when their helpers don’t already live in `lib/data/`.**

What *doesn’t* go in server-only directories: utility functions used by both server and client (formatters, validators, type definitions). Those live in `src/lib/utils/` or `src/lib/types/` and don’t need the `server-only` import.

## Anti-patterns

**Mixing client-safe and server-only code in the same file.** A `lib/utils/format.ts` file with both `formatCurrency()` (safe) and `getFormattingConfigFromDatabase()` (server-only) is a leak waiting to happen. Split the file.

**Routing all data access through a single `lib/data/index.ts`.** A barrel export that re-exports everything makes it harder for the bundler to tree-shake and harder for a reader to know what’s safe. Import from specific files.

**Using `'use server'` as a substitute for `server-only`.** `'use server'` marks a file as containing server actions; it doesn’t prevent the file from being imported by client components. Only `server-only` does that. (`'use client'` is the inverse direction; it doesn’t help here.)

**Allow-listing the whole `lib/` directory.** Some code in `lib/` is genuinely shared. The convention guard should target the directories that are unambiguously server-only.

**Forgetting to update the convention guard’s directory list when adding a new server-only module.** A new module’s data directory needs to be added to the guard’s `SERVER_ONLY_DIRECTORIES` array. Otherwise the guard isn’t covering it.

## Negative consequences

- **Two-layer defense is more setup than one.** A team that’s just shipping prototypes might skip both. Acceptable for prototypes; required for anything with secrets.
- **The convention guard’s directory list is project-specific.** It has to be updated as the project’s structure evolves. Mitigation: make adding a new server-only directory part of the spec when a new module is created.
- **`server-only` is Next.js-specific.** Other frameworks have similar primitives (e.g., Remix’s loaders are server-only by convention; SvelteKit’s `+server.ts` files). The principle generalizes; the specific import doesn’t.
- **The guard uses `require('fs').readFileSync` synchronously.** For a large codebase, this can be slow. Mitigation: cache the file list, run the guard in a separate test suite that doesn’t run on every save.

## Verification

Run a deliberate-violation pass:

1. Add a new file under `src/lib/data/` *without* the `server-only` import.
2. Run the test. Confirm it fails with a message naming the file.
3. Add the import. Confirm green.

For the bundler-level defense:

1. Add an `'use client'` component that imports a `lib/data/` function.
2. Run `npm run build`. Confirm the build fails with a server-only import violation.
3. Remove the import. Confirm the build passes.

This proves both layers engage with real misuse.

## Related

- `convention-guard-tests` — the general shape of the directory-coverage test.
- `principles/defense-in-depth-authorization.md` — the philosophical basis for layered defenses (this is one of the layers).
