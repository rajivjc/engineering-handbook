## ADR-013: Deliberate-violation verification as standard audit practice

**Status:** Accepted
**Date:** 2026-05-04 [Session 24b1-fix; formalized after the RLS pattern guard caught a real leak]

**Context**
A test that’s supposed to catch a class of bug only earns trust if you can show it actually fails when the bug is reintroduced. A test that “always passes” is functionally untested. Three sessions in a row shipped tests that were later discovered to be passing regardless of whether the underlying check was working: an RLS guard that matched the function name appearing anywhere in a policy clause body (missing the case where it appeared in only one OR-branch); a CSV precision test that passed regardless of whether the implementation rounded sum-of-rounded or round-of-sum; an atomicity test where the throw was injected at the function-call boundary and the rollback path was never exercised.

**Decision**
For any institutional-memory work — security guards, atomicity tests, regression spies — the audit step **must** include a deliberate-violation pass:

1. Revert the fix you just landed.
1. Run the test.
1. Confirm it fails — and fails for the right reason.
1. Restore the fix.

If the test passes when the fix is reverted, the test is wrong. The fix doesn’t ship until the test is genuinely engaging. The deliberate-violation step is documented in the commit message of any institutional-memory work.

**Consequences**

- **Several near-misses caught after the discipline became standard.** The strengthened RLS NULL-coalescence guard caught a critical leak that the original regex would have missed. The Proxy-on-mutation-target pattern was identified after a deliberate-violation pass on an atomicity test revealed the test passed regardless of whether the rollback was correct.
- **Cultural shift.** “Did you deliberate-violate it?” became a routine audit question. The mental model of testing shifted from “I wrote a test that passes” to “I wrote a test that I demonstrated fails for the bug I care about.”
- **Negative: audit time roughly doubles for security-critical changes.** The deliberate-violation step itself is fast (revert, run, restore — under a minute), but the required care around what to revert and what to leave in place takes time to think through.
- **Negative: the discipline is hard to enforce automatically.** It’s a habit at the audit step, not a CI check. A motivated person can claim to have deliberate-violated when they didn’t. The mitigation is honesty culture and including the deliberate-violation log in the audit findings.
- **Negative: it surfaces ugly truths.** Several existing tests were found to be broken when the discipline was applied retroactively. Fixing them was real work that didn’t ship features. Worth doing; not free.
