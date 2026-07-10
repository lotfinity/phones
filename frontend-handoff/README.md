# PriceBridge frontend data handoff

This folder contains a **curated, normalized design fixture** for building a completely new detachable frontend.

## Attach these files to the design prompt

1. `opportunities.sample.json` — realistic cross-category UI data.
2. `opportunity.schema.json` — the machine-readable contract.
3. `cleanup-report.json` — what was normalized, retained, and deliberately omitted.

The source exports remain unchanged. They are operational outputs and contain category-specific field names, duplicated/incomplete variants, and records that still need review. The sample fixture is intentionally safer and easier for a design model to understand.

## Important

- This is a frontend design fixture, not a live trading feed.
- Evidence arrays are capped to keep the attachment compact. Original listing counts are preserved.
- Warning flags are intentional. They allow the frontend to design low-confidence, incomplete-variant, thin-margin, and mixed-evidence states.
- Components should consume the normalized contract rather than directly depending on the three legacy export shapes.
- Keep the data access layer replaceable so local fixtures can later be swapped for Django REST endpoints.

## Recommendation values

- `strong_opportunity`
- `good_opportunity`
- `watch`
- `weak_evidence`
- `avoid`

## Category-specific specifications

Read fields from `specifications` and render them according to `category`.

- Phone: storage, RAM, SIM, battery, box status, condition.
- Laptop: CPU, GPU, RAM, storage, screen details.
- Portable console: chipset, RAM, storage, screen details.

Missing values must render as unavailable, not as zero.
