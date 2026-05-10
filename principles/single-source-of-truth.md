# Principle: Single source of truth

When a value flows to multiple surfaces (PDF, JSON, CSV, UI), define it once and project from there. The pattern is: a single transformer function takes the raw data and produces the canonical document; every surface consumes the canonical document.

This is not the same as “DRY.” It’s stronger. The point isn’t to avoid repeating yourself. It’s to make divergence between surfaces impossible by construction.

## What this looks like

The wrong shape:

```ts
// PDF route
const totalGross = lineItems.reduce((sum, li) => sum + li.cents, 0)
const totalGrossFormatted = `S$${(totalGross / 100).toFixed(2)}`

// CSV export
const totalGross = lineItems.reduce((s, l) => s + l.cents, 0) / 100
const totalGrossString = totalGross.toFixed(2)

// Staff UI summary
const total = lineItems.map(l => l.cents).reduce((a, b) => a + b)
const formatted = `S$${(total / 100).toLocaleString()}`
```

Three surfaces, three implementations, three subtly different formatting decisions. They produce the same number for the test fixture but will diverge under any of: localized number formatting, currency rounding edge cases, line-item filtering changes, summation order changes (relevant for floating point — though here we’re in integer cents, so less so).

The right shape:

```ts
// One transformer
export function buildPayslipDocument(run, staff, lineItems): PayslipDocument {
  const totalGrossCents = lineItems.reduce((sum, li) => sum + li.amount_cents, 0)
  return {
    runId: run.id,
    staffId: staff.id,
    period: { start: run.period_start, end: run.period_end },
    lineItems: lineItems.map(li => ({
      label: li.label,
      kind: li.kind,
      amountCents: li.amount_cents,
    })),
    totals: {
      grossCents: totalGrossCents,
      grossFormatted: formatSGD(totalGrossCents),
    },
    // ... other fields
  }
}

// PDF route
const doc = buildPayslipDocument(run, staff, lineItems)
return renderPayslipPDF(doc)

// CSV export
const doc = buildPayslipDocument(run, staff, lineItems)
return doc.totals.grossCents  // or grossFormatted, depending on column

// Staff UI summary
const doc = buildPayslipDocument(run, staff, lineItems)
return <Summary doc={doc} />
```

Now the totals are computed once, formatted once, and consumed everywhere. A change to how totals are computed changes one function. A reader who wants to know what’s on a payslip reads one type definition.

## Why this earns its keep

- **Consistency by construction.** Three surfaces showing the same number is a property of the code structure, not a property of vigilance.
- **Testability.** The transformer is a pure function. Testing the totals logic is testing one function with concrete inputs and outputs. Testing each surface separately is testing three things, and missing the case where they disagree.
- **Localization-ready.** Currency formatting, date formatting, number formatting — all in the transformer. Surface code consumes formatted strings, not raw numbers. Adding a second locale is changing the formatter, not three call sites.
- **Refactoring safety.** When the schema changes (a new line-item kind, a deduction column, a different rounding rule), the transformer changes. The surfaces don’t notice unless their type contract changes. The blast radius of a change is bounded.

## What counts as a “surface”

Anything that displays, exports, or transmits the value. PDF generation, CSV export, JSON API response, server-rendered HTML, client-side React component, email body, push notification payload, audit log entry. They all count.

If the value flows to one surface only, this principle doesn’t apply yet. Add it when the second surface lands.

## Anti-patterns

- **Computing the value in the database query.** Sometimes appropriate (when the database does the math anyway), often premature. The database query is one of many surfaces; if you compute the totals there, you’ve made the database the transformer. Sometimes that’s right; often it’s not.
- **Per-surface adapters that look like transformers but aren’t.** “I have a `payslipForPDF` and a `payslipForCSV` function” is not single-source-of-truth. They might do the same thing today; they will diverge tomorrow.
- **The transformer that grows to include surface-specific logic.** “If the surface is PDF, format the date as `YYYY-MM-DD`; if CSV, format as `dd-mm-yyyy`.” This is the transformer becoming three transformers in disguise. Either the date should be the same on both surfaces (likely) or the formatting belongs in the surface code (sometimes).

## Negative consequences

- The transformer can grow large for complex documents. A payslip with line items, deductions, year-to-date totals, branding fields, and signature blocks is a non-trivial type definition.
- The pattern requires upfront design when the second surface arrives. Refactoring “we have three duplicate computations” into “one transformer feeding three surfaces” is real work.
- Sometimes the surfaces genuinely need different shapes — a CSV row is flatter than a PDF page. The transformer might produce a richer document than any single surface needs, with each surface picking its fields. This is the right pattern but it’s not free; you’re carrying fields that only some surfaces use.

The cost is small relative to the cost of three implementations diverging in production with different totals on the staff UI than on the PDF.

## Where this is enforced

[`patterns/universal/single-source-of-truth-transformer.md`](../patterns/universal/single-source-of-truth-transformer.md) documents the pattern with the payslip-transformer worked example, including the regression test that asserts the PDF and the staff UI show identical totals for the same input.
