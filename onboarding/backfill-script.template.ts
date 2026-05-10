/**
 * One-off backfill script: {{BRIEF DESCRIPTION}}
 *
 * Why: {{Reason this script exists. What changed in the schema or business
 * logic that requires backfilling.}}
 *
 * Idempotent: {{Yes/No, with rationale}}.
 *
 * Usage:
 *   npx tsx scripts/{{filename}}.ts
 *
 * Requires env vars: NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
 */

import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY

if (!supabaseUrl || !serviceRoleKey) {
  console.error('Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY')
  process.exit(1)
}

const adminClient = createClient(supabaseUrl, serviceRoleKey)

async function main() {
  console.log('Starting backfill...\n')

  // 1. Count affected rows (sanity check before mutating)
  // const { count, error: countError } = await adminClient
  //   .from('your_table')
  //   .select('*', { count: 'exact', head: true })
  //   .filter('your_filter', 'is', 'something')

  // 2. Apply the backfill in batches if the dataset is large.
  //    For datasets < ~10k rows, a single update is fine. For larger,
  //    paginate and apply in chunks of ~500 rows.

  // 3. Log progress periodically.

  console.log('\nBackfill complete.')
}

main().catch(err => {
  console.error('Backfill failed:', err.message)
  process.exit(1)
})
