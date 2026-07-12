# Bagisto UI Port

A preservation-first workspace for capturing, cleaning, analyzing, and previewing the Bagisto Headless Electronic storefront UI.

The goal is **not to redesign or rebuild the storefront**. The captured HTML structure, utility classes, responsive layout, typography, drawers, product presentation, and account views are treated as the visual source of truth. A future Django pass should parameterize this existing markup with template variables, loops, URL tags, forms, and seeded data while keeping the appearance intact.

## Current state

This repository contains reference captures for:

- Homepage, including a logged-in state
- Homepage with the authenticated Account drawer visibly open
- Product listing/category page
- Multiple product detail examples
- Customer registration
- Customer profile/account page
- Shared header, search drawer, cart drawer, mobile navigation, service strip, and footer states

The cleaned pages use the extracted Bagisto stylesheet plus a small vanilla JavaScript compatibility runtime. That runtime restores interactions that were originally controlled by React/Next.js and were removed during cleaning.

Implemented compatibility behavior includes:

- Light/dark theme switching and persistence
- Search and cart drawers
- Mobile navigation actions
- Product image thumbnail selection
- Quantity controls
- Registration listbox behavior
- Font compatibility fixes

## Repository layout

```text
analysis/                 HTML/CSS coverage reports and extracted sections
assets/
  css/                    Extracted theme CSS and compatibility fixes
  css/fonts/              Bundled Archivo font files
  js/                     Small vanilla storefront runtime
captures/                 Original SingleFile captures and preserved sources
pages/                    Clean pages and browser-ready previews
tools/                    Capture, clean, analyze, and preview-generation tools
```

## Install

```bash
npm ci
```

## Preview the captured pages

```bash
npm run serve
```

Then open the relevant files under `http://localhost:8080/pages/`.

Common examples:

```text
/pages/smartphones-preview.html
/pages/products/speakers-preview.html
/pages/customer/register-preview.html
/pages/private/customer-profile-preview.html
/pages/home/index-logged-in-preview.html
/pages/home/account-drawer-reference.html
```

## Refresh shared assets in previews

```bash
npm run refresh-previews
```

This reinjects the shared theme CSS, compatibility CSS, theme bootstrap, and vanilla runtime into every `*-preview.html` file.

## Capture a public route

```bash
tools/process-route.sh GROUP NAME --url "https://example.com/route"
```

Example:

```bash
tools/process-route.sh customer login \
  --url "https://bagisto-headless-electronic.vercel.app/customer/login"
```

## Import a locally saved authenticated page

```bash
tools/process-route.sh GROUP NAME --local "/absolute/path/to/page.html"
```

Authenticated pages should be saved through the SingleFile browser extension while the desired drawer, menu, tab, or responsive state is visibly open.

## Account-drawer source

The open authenticated Account drawer is preserved losslessly as a compressed source. Regenerate its complete decoded capture, clean page, analysis, and preview with:

```bash
node tools/process-open-account-capture.mjs
```

A lightweight immediately viewable reference is available at:

```text
pages/home/account-drawer-reference.html
```

## Django handoff

The intended next stage is a mechanical Django conversion:

- Keep existing HTML and class names
- Replace hardcoded content with `{{ variables }}`
- Replace repeated records with `{% for %}` loops
- Add `{% url %}`, `{% static %}`, CSRF, and Django forms where necessary
- Extract duplicated shell markup into includes without changing its design
- Render fixture or seeded data before implementing full commerce behavior

No Django project, model contract, cart backend, checkout flow, or production integration is included yet.

See [DESIGN.md](DESIGN.md) for the preservation rules, architecture notes, and recommended continuation point.

## Source reference

The visual reference was captured from:

```text
https://bagisto-headless-electronic.vercel.app/
```

This repository is an implementation/reference workspace and is not presented as the upstream Bagisto project.
