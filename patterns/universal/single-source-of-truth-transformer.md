# Single-source-of-truth transformer

**Category:** universal
**Applies to:** values that flow to multiple surfaces — UI, PDF, CSV, JSON API response, server-rendered HTML, push notification payload, audit log.

This is the implementation pattern for the principle of the same name. The principle (`principles/single-source-of-truth.md`) covers the *why*. This file covers the *how*.

## The shape

One transformer function consumes raw data and produces a canonical document. Every surface consumes the canonical document. No surface computes anything from the raw data directly.

```ts
// src/lib/payroll/build-payslip-document.ts

export interface PayslipDocument {
  runId: string
  staffId: string
  staffName: string
  period: { startISO: string; endISO: string; label: string }
  lineItems: PayslipLineItemDoc[]
  totals: {
    grossCents: number
    grossFormatted: string  // formatted in the venue's locale
    netCents: number
    netFormatted: string
  }
  generatedAtISO: string
}

export interface PayslipLineItemDoc {
  label: string
  kind: 'regular' | 'overtime' | 'allowance' | 'deduction'
  hours: number | null
  rateCents: number | null
  amountCents: number
  amountFormatted: string
}

export function buildPayslipDocument(
  run: PayrollRun,
  staff: Staff,
  rawLineItems: PayslipLineItem[],
  config: { locale: string; currency: string }
): PayslipDocument {
  const lineItems: PayslipLineItemDoc[] = rawLineItems.map(li => ({
    label: li.label,
    kind: li.kind,
    hours: li.hours,
    rateCents: li.rate_cents,
    amountCents: li.amount_cents,
    amountFormatted: formatMoney(li.amount_cents, config),
  }))

  const grossCents = rawLineItems
    .filter(li => li.kind !== 'deduction')
    .reduce((sum, li) => sum + li.amount_cents, 0)
  const deductionCents = rawLineItems
    .filter(li => li.kind === 'deduction')
    .reduce((sum, li) => sum + li.amount_cents, 0)
  const netCents = grossCents - deductionCents

  return {
    runId: run.id,
    staffId: staff.id,
    staffName: staff.full_name,
    period: {
      startISO: run.period_start,
      endISO: run.period_end,
      label: formatPeriodLabel(run.period_start, run.period_end, config),
    },
    lineItems,
    totals: {
      grossCents,
      grossFormatted: formatMoney(grossCents, config),
      netCents,
      netFormatted: formatMoney(netCents, config),
    },
    generatedAtISO: new Date().toISOString(),
  }
}
```

Then every surface is a consumer:

```tsx
// PDF route
const doc = buildPayslipDocument(run, staff, lineItems, config)
return renderPayslipPDF(doc)

// CSV export — one row per payslip
const doc = buildPayslipDocument(run, staff, lineItems, config)
return [doc.staffId, doc.staffName, doc.totals.grossFormatted, doc.totals.netFormatted]

// Staff UI summary
const doc = buildPayslipDocument(run, staff, lineItems, config)
return <PayslipSummary doc={doc} />

// JSON API response
const doc = buildPayslipDocument(run, staff, lineItems, config)
return Response.json(doc)
```

A change to how totals are computed changes *one function*. A change to how money is formatted changes *one helper*. Three surfaces showing the same number is a property of the structure, not vigilance.

## What goes in the document vs. the surface

**In the document:**

- Computed values (totals, deductions, percentages).
- Formatted values (currency strings, dates, percentages).
- Localization-affected output (formatted dates depend on locale).
- Anything that more than one surface displays.

**In the surface:**

- Layout (which fields go in which column on a CSV vs. which section on a PDF).
- Surface-specific styling (font size, color).
- Surface-specific behaviour (interactive vs. static).

The rule of thumb: if changing how it’s *computed* should change how all surfaces show it, it’s in the document. If changing how it’s *displayed* on one surface shouldn’t affect others, it’s in the surface.

## When to introduce the transformer

The honest answer: when you have the second surface. With one surface, the transformer is overhead.

The wrong answer: “we’ll add the transformer when we add the second surface.” When the second surface lands, you’ll be under deadline pressure and the existing surface’s logic will be intertwined with display concerns. Refactoring is harder than starting fresh.

The pragmatic answer: as soon as you can predict a second surface is coming, build the transformer. Most non-trivial values flow to at least two surfaces (the UI and either an export or an API). Predicting this isn’t hard.

## Tests for the transformer

The transformer is a pure function. Test it the way `pure-function-test-isolation` describes: a table of input cases, each producing a known output.

Critically, add a test that asserts surfaces stay in sync:

```ts
it('PDF totals match staff UI totals match CSV totals', () => {
  const doc = buildPayslipDocument(run, staff, lineItems, { locale: 'en-SG', currency: 'SGD' })
  const pdfTotal = extractTotalFromPDF(renderPayslipPDF(doc))
  const uiTotal = extractTotalFromUI(<PayslipSummary doc={doc} />)
  const csvTotal = extractTotalFromCSV([renderPayslipCSV(doc)])

  expect(pdfTotal).toBe(doc.totals.grossFormatted)
  expect(uiTotal).toBe(doc.totals.grossFormatted)
  expect(csvTotal).toBe(doc.totals.grossFormatted)
})
```

This test is the structural enforcement of single-source-of-truth. If a contributor adds a surface that computes its own total, the test fails (the computed total won’t match the document’s total).

## Anti-patterns

**Per-surface adapters that look like transformers.** `buildPayslipForPDF()`, `buildPayslipForCSV()`, `buildPayslipForUI()`. Each does the same thing today. Tomorrow they diverge. The whole point of the transformer is that all surfaces consume the *same* document; per-surface adapters are three transformers in disguise.

**Computing values in the database query.** Sometimes the right call (when the database does the math anyway). Often premature. The query is one of many surfaces; computing totals there means the database is now your transformer, and any future surface that needs the totals has to re-query the database (or duplicate the computation). The transformer in the application code, fed by the query, generalizes better.

**Surface-specific logic creeping into the transformer.** “If the surface is PDF, use one date format; if CSV, use another.” The transformer is now branched by surface; you’ve reintroduced the per-surface variant problem. Either the date should be the same on both surfaces (likely) or the formatting belongs in the surface (sometimes).

**Letting the document grow large.** If the document carries every possible field every surface might want, it gets fat. Mitigation: derive the document fields from the union of what surfaces actually use. If only one surface uses a field, ask whether the field belongs in the surface code instead.

## Negative consequences

- **One more layer.** A reader has to follow: surface → document → transformer → raw data. More indirection than “surface reads from raw data directly.”
- **Document type can grow.** A complex document (a payslip with line items, year-to-date totals, deductions, branding fields) is a non-trivial type definition. The cost is real.
- **Sometimes one surface needs a field no other surface needs.** The document carries the field anyway; the surfaces ignore it. Acceptable cost in exchange for the consistency guarantees.
- **Refactoring an existing duplicated codebase is real work.** Three duplicate computations don’t merge into a transformer for free. Plan a session for the consolidation; don’t tack it onto a feature.

## Verification

For any value that flows to multiple surfaces, verify the consistency test exists. If it doesn’t, the audit logs a finding. Periodically (audit time) run a deliberate-violation pass: change the computation in the transformer, confirm all surfaces update; change the formatting in one surface only, confirm the consistency test fails.

## Related

- `principles/single-source-of-truth.md` — the principle behind this pattern.
- `pure-function-test-isolation` — the transformer is a pure function and is tested as such.
