# Dynamic config from DB

**Category:** web
**Applies to:** values that vary per tenant, per environment, or per deployment that you’d otherwise be tempted to hardcode (timezone, locale, currency, club name, branding, feature flags).

## Problem

Many web apps grow configuration values that “should be the same everywhere” — until they aren’t. A few common shapes:

- A scheduling app hardcodes `'Asia/Singapore'` because it was built for a Singapore venue. Two months later, a second venue wants to use the app from Australia. Now there are 47 places where the timezone is hardcoded.
- A club app hardcodes the club name in PDFs, emails, and pages. Same future problem.
- A payment app hardcodes `'SGD'` and `'en-SG'`. The next customer is in Indonesia.

The conventional fix is “search and replace, refactor as you go.” This works once. The second time you have to do it, you should have made the value dynamic the first time.

## Mechanism

For values that vary per tenant or per deployment, store them in a single configuration row in the database and read them at request time:

```sql
-- Dedicated config table; one row per "tenant" (could be one row total
-- for a single-venue app, more for multi-tenant).
create table tenant_config (
  id uuid primary key default gen_random_uuid(),
  -- ... other columns
  name text not null,
  timezone text not null default 'UTC',
  locale text not null default 'en-US',
  currency text not null default 'USD',
  branding_logo_url text,
  branding_footer_text text,
  -- ... more
  updated_at timestamptz not null default now()
);

-- For a single-tenant app, you can enforce singleton:
create unique index tenant_config_singleton on tenant_config ((true));
```

Read the config in a server-side helper:

```ts
// src/lib/config.ts
import 'server-only'
import { cache } from 'react'
import { getServerClient } from '@/lib/supabase/server'

export interface TenantConfig {
  id: string
  name: string
  timezone: string  // e.g., 'Asia/Singapore'
  locale: string    // e.g., 'en-SG'
  currency: string  // e.g., 'SGD'
  brandingLogoUrl: string | null
  brandingFooterText: string | null
}

export const getTenantConfig = cache(async (): Promise<TenantConfig> => {
  const supabase = await getServerClient()
  const { data, error } = await supabase
    .from('tenant_config')
    .select('*')
    .single()

  if (error || !data) {
    // Build-time fallback — this is the only place a hardcoded default lives,
    // and it exists so the app still compiles when the database is unreachable.
    return {
      id: 'fallback',
      name: 'My App',
      timezone: 'UTC',
      locale: 'en-US',
      currency: 'USD',
      brandingLogoUrl: null,
      brandingFooterText: null,
    }
  }

  return {
    id: data.id,
    name: data.name,
    timezone: data.timezone,
    locale: data.locale,
    currency: data.currency,
    brandingLogoUrl: data.branding_logo_url,
    brandingFooterText: data.branding_footer_text,
  }
})
```

`cache` is React 19’s request-scoped memoization — multiple calls during a single request hit the database once. Per-request caching is the right granularity: the config can change between requests, but reads within a request see a consistent view.

For client components, expose the config via a context provider:

```tsx
// src/components/providers/TenantConfigProvider.tsx
'use client'
import { createContext, useContext } from 'react'
import type { TenantConfig } from '@/lib/config'

const TenantConfigContext = createContext<TenantConfig | null>(null)

export function TenantConfigProvider({
  config,
  children,
}: {
  config: TenantConfig
  children: React.ReactNode
}) {
  return <TenantConfigContext.Provider value={config}>{children}</TenantConfigContext.Provider>
}

export function useTenantConfig(): TenantConfig {
  const config = useContext(TenantConfigContext)
  if (!config) throw new Error('useTenantConfig must be used within TenantConfigProvider')
  return config
}
```

The provider wraps the root layout, fed the config from the server:

```tsx
// src/app/layout.tsx
import { getTenantConfig } from '@/lib/config'
import { TenantConfigProvider } from '@/components/providers/TenantConfigProvider'

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const config = await getTenantConfig()
  return (
    <html lang={config.locale.split('-')[0]}>
      <body>
        <TenantConfigProvider config={config}>{children}</TenantConfigProvider>
      </body>
    </html>
  )
}
```

Now any client component can read the config:

```tsx
'use client'
import { useTenantConfig } from '@/components/providers/TenantConfigProvider'

export function PriceTag({ priceCents }: { priceCents: number }) {
  const { locale, currency } = useTenantConfig()
  return <span>{new Intl.NumberFormat(locale, { style: 'currency', currency }).format(priceCents / 100)}</span>
}
```

## What goes in the config vs. environment variables

**Config table (database):**

- Tenant-specific values that might change per deployment or after launch.
- Branding, name, locale, timezone, currency.
- Feature flags scoped to the tenant.
- Per-tenant rules (e.g., “minimum booking duration”).

**Environment variables:**

- Secrets (API keys, signing secrets, service role tokens).
- Build-time configuration (Vercel-specific values).
- Connection details that depend on where the app is running.
- Anything that must be available before the database is reachable.

The line is “what does the application need to know before it can talk to the database?” Those are env vars. Everything else is config.

## Enforcing the discipline

The convention guard test (`convention-guard-tests`) catches drift:

```ts
// tests/conventions/no-hardcoded-config.spec.ts
const FORBIDDEN = [
  "'Asia/Singapore'",
  '"Asia/Singapore"',
  "'en-SG'",
  '"en-SG"',
  "'SGD'",
  '"SGD"',
]

const ALLOW_LIST = [
  { file: 'src/lib/config.ts', reason: 'build-time fallback when DB is unreachable' },
  { file: 'src/components/providers/TenantConfigProvider.tsx', reason: 'context default' },
]

// ... grep for FORBIDDEN, subtract ALLOW_LIST, fail on remainder
```

The test fires on any new hardcoded value. Allow-list entries require justification. The discipline becomes automated.

## Why dynamic config now beats “we’ll make it dynamic later”

The “later” version requires:

1. Find every hardcoded value (47 places).
1. Add a config provider.
1. Update each hardcoded value to read from config.
1. Test the migration; confirm no behaviour changed.
1. Add the convention guard.

Doing this proactively requires only step 5, plus the small infrastructure of the provider. The cost is upfront and small. The cost of doing it later is large and recurring (you’ll catch new hardcoded values for months as you discover them).

If you’re confident the project is single-tenant single-deployment forever, hardcoding is fine. Most projects aren’t, and “we’ll make it dynamic later” is the most expensive version of “we’ll do it eventually.”

## Anti-patterns

**Multiple sources of truth.** A timezone in `tenant_config.timezone`, a locale in a separate `i18n_config` table, a currency in environment variables. Three things to read, three places to update. Consolidate.

**Re-reading the config on every component.** Without `cache` or context, every server component fetches the config from the database, and every client component re-renders if the config object reference changes. Use the cache + provider shape above.

**Letting null fields propagate to the UI.** A nullable branding URL means every consumer must handle null. Either give it a default in the type (provider populates the default), or handle null in one place (a `BrandingLogo` component that knows what to render when null).

**Storing build-time secrets in the config table.** API keys go in env vars, not in the database. Anything readable by the runtime application (with whatever auth the app has) shouldn’t be in the config table.

**Hot-reload-on-config-change without thinking through the implications.** “When the config changes, every active session sees the new value.” This sounds good until a user is mid-booking when the timezone switches. Plan for the gradual rollout — the config typically changes rarely, and `cache` ensures requests in flight see a consistent view.

## Negative consequences

- **One more table to manage.** Migrations include the config table. Seeds populate it. Tests need fixtures for it.
- **One more layer of indirection.** A reader chasing “where does the timezone come from?” follows config.ts → tenant_config table → wherever the row was last updated.
- **Build-time fallback can drift.** The fallback values in `getTenantConfig()` exist for the unreachable-DB case but aren’t kept up to date with the actual production values. Periodically audit them.
- **Clients can’t change the config.** The pattern assumes config changes are admin actions. If you want users to “set their preferences” individually, that’s a different table (per-user preferences) layered on top of the tenant config.

## Verification

The convention guard test catches new hardcoded values. Audit-time spot-check verifies that user-facing strings (button labels, error messages, currency symbols) come from config or are deliberately language-agnostic.

For a deliberate-violation pass: temporarily change `tenant_config.timezone` from `'Asia/Singapore'` to `'America/New_York'`. Reload the app. Confirm dates render in Eastern time across every page. If any page still shows Singapore time, that page is bypassing the config — file a finding.

## Related

- `convention-guard-tests` — the test that prevents hardcoded values from creeping back in.
- `single-source-of-truth-transformer` — same philosophy, different scope (this is for config; the transformer is for derived values).
