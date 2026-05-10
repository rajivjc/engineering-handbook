# Engineering Handbook vs. GitHub Spec-Kit

Both projects sit in the same neighbourhood — spec-driven development with AI coding agents — but solve different problems. This page exists because the question is asked.

## Where they overlap

- Both treat specifications as primary artifacts, not afterthoughts.
- Both target AI-assisted development as the primary execution mode.
- Both maintain a “constitution” or project-intelligence file that the agent reads at the start of every session.
- Both produce ADR-style decision records.

## Where they diverge

|Dimension          |Spec-Kit                                                         |Engineering Handbook                           |
|-------------------|-----------------------------------------------------------------|-----------------------------------------------|
|**Shape**          |CLI + slash commands + templates                                 |Opinionated Markdown + agent skills            |
|**Mode**           |Greenfield-optimized                                             |Mature-codebase-tested                         |
|**Substrate**      |Tooling and ergonomics                                           |Discipline and evidence                        |
|**Coverage**       |Workflow templates and structure                                 |What survives audits over many sessions        |
|**Adoption cost**  |Install, learn the slash commands                                |Read, internalize five principles              |
|**Lock-in**        |Couples your workflow to spec-kit’s evolution (currently pre-1.0)|None — applies to any agent that reads Markdown|
|**Network effects**|Active community extensions, presets                             |None                                           |
|**Backed by**      |GitHub                                                           |Solo evidence from real projects               |

## Where the handbook is stronger

- **Evidence-based.** Every pattern has the bug that motivated it. Spec-Kit gives you templates to fill in; the handbook tells you what good looks like once filled.
- **Tooling-agnostic.** Works with Claude Code, Cursor, Codex, Aider, Copilot — anything that reads Markdown. Not coupled to a specific CLI.
- **Captures meta-disciplines.** “Deliberate-violation verification” — revert your fix to confirm the test actually catches the bug — isn’t expressible as a template. It’s a habit, documented as one. Same for the audit-by-deliberate-violation discipline that runs on every session.
- **Built from real production projects.** The patterns survived 27+ sessions and audit-clean Phase 3 on a real-money venue app. That track record isn’t claimed; it’s [linked from a real repo](https://github.com/rajivjc/Tigress) with public commit history.
- **Honest about negative consequences.** ADRs include negative consequences explicitly. Patterns include the ergonomic cost. Anyone reading this should leave with a calibrated view, not a sales pitch.

## Where Spec-Kit is stronger

- **Ergonomics.** Slash commands give you a workflow in seconds. The handbook gives you a stance — you still write the prompt yourself.
- **Onboarding speed.** A new developer with no opinions can install Spec-Kit and start producing. The handbook assumes you already have or want to develop opinions.
- **Community.** Extensions for Jira, Confluence, Azure DevOps, security review, V-Model traceability — built by other people, available now. The handbook has no extension ecosystem.
- **Maintained funding.** GitHub-backed, real maintenance, real velocity. The handbook is one developer’s body of work.

## How to layer them

If you use Spec-Kit for the workflow ergonomics:

- Keep `/speckit.specify`, `/speckit.plan`, `/speckit.tasks`, `/speckit.implement` for the loop.
- Replace the default `/speckit.constitution` content with the handbook’s principles and the relevant project-specific patterns from `patterns/`.
- Bring `process/four-step-verification-gate.md` and `process/audit-methodology.md` in as the gate before any commit.
- Use the three case studies as worked examples for what `/speckit.analyze` should be catching.
- Treat `decisions/` as the seed for your project’s ADR directory.

If you don’t use Spec-Kit:

- The handbook is independent. Bring patterns in as Markdown for humans, or as `skills/` for agent-loadable context.
- The `onboarding/spec-prompt.template.md` is a standalone replacement for the structured session prompts that Spec-Kit’s slash commands generate.

## An honest take

I considered adopting Spec-Kit retroactively for one of my projects (Tigress, a production club management platform). I didn’t, for two reasons:

1. The codebase already had its own SDD discipline — different file names, same shape. Migrating to Spec-Kit was busywork without a clear payoff. The audit findings before and after would have been the same; only the cosmetic structure would change.
1. Spec-Kit at v0.8 is a moving target with an active issue tracker. For a side project with mid-term commercialization plans, coupling tightly to a pre-1.0 tool felt premature. After 1.0, this calculus changes.

The handbook is what I extracted instead — the patterns the project produced, generalized for other projects. If you’re starting greenfield and want ergonomics, use Spec-Kit. If you want a stance and the evidence behind it, take the handbook. If you want both, layer them.
