Audit-prompt format. After Claude Code lands a session commit, paste this into a fresh Claude Chat session (or equivalent) with `[N]` replaced by the session number. The structure pushes toward the disciplines documented in the handbook’s `process/audit-methodology.md`.

---

```
Session [N] is done. Please audit and verify.

Workflow:
1. Pull the latest from main: `git pull --rebase`
2. Show recent commits: `git log --oneline -5`
3. For the session's commit, run `git show --stat [hash]` to see what changed
4. Run the four-step build verification:
   - `npx tsc --noEmit`
   - `npm run build`
   - `npm run lint`
   - `npx vitest run`
5. Spot-check pass A: pick 3 claims from the session's deliverables and verify each is traceable to actual code.
6. Spot-check pass B: pick 3 file references in the new content and verify those files exist.
7. Spot-check pass C: if the session adds tests for institutional-memory work (security guards, atomicity, regression spies), perform deliberate-violation verification on one of them: revert the fix, run the test, confirm failure, restore.
8. Findings classification: critical / medium / lower / observation. Critical and medium block; lower and observation can defer.

For each finding, include:
- Severity
- What's wrong
- Where it's wrong (file:line if applicable)
- Recommended fix

Report verification status, line counts (if relevant), spot-check results, and findings. End with a recommendation: ship as-is, ship after small fix, or back to a fix-up session.
```

---

The audit prompt assumes the agent has tools for running shell commands and reading files. If your agent doesn’t, run the verification commands yourself and paste outputs into the chat with the rest of the audit framing.
