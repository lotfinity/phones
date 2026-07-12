# Design and Handoff Notes

## 1. Purpose

This repository preserves the visual and structural behavior of the Bagisto Headless Electronic storefront so it can later be rendered by Django.

The central rule is simple:

> Preserve the existing storefront markup and appearance; parameterize it rather than redesigning it.

The cleaned captures are the primary visual specification. The extracted CSS, fonts, and captured responsive states should remain authoritative unless a change is deliberately requested.

## 2. Non-goals

This workspace does not currently attempt to:

- Redesign the storefront
- Recreate the UI from a component library
- Replace the captured utility classes with a new CSS system
- Implement checkout, payments, orders, or fulfillment
- Finalize product, variant, inventory, customer, or cart models
- Reproduce the complete original React/Next.js application runtime

## 3. Preservation rules

A Django conversion should follow these rules:

1. Keep the existing element hierarchy whenever practical.
2. Keep existing class names and responsive breakpoints.
3. Keep the existing desktop and mobile layouts.
4. Keep the existing light/dark styling strategy.
5. Keep image aspect ratios and gallery structure.
6. Keep drawers, overlays, navigation, and form layouts visually consistent.
7. Replace only hardcoded content, URLs, state, and repeated records.
8. Extract duplicated markup into includes only when the output HTML remains equivalent.

## 4. Current architecture

### Captures

Original pages are stored under `captures/`. Public routes can be captured through SingleFile CLI. Authenticated or transient UI states are saved through the browser extension and then imported locally.

### Analysis

The tools compare HTML classes against the extracted compiled stylesheet and produce reports under `analysis/`. These reports identify:

- Class coverage
- Missing classes
- Interactive elements
- IDs and tag frequencies
- Clean body/main fragments
- Extracted structural sections

Coverage across the representative pages is high enough that the shared compiled CSS should remain the default stylesheet.

### Clean pages

Framework runtime, embedded scripts, and capture-specific artifacts are removed to create clean structural references under `pages/`.

### Shared runtime

`assets/js/site-shell.js` restores a limited set of interactions without React:

- Theme switching
- Search/cart drawer behavior
- Mobile navigation actions
- Product gallery thumbnails
- Quantity controls
- Listbox behavior

This runtime is a preview and migration aid. During Django integration it may remain as-is, be split into smaller modules, or be replaced by progressively enhanced Django/HTMX/vanilla behavior. The rendered appearance should not change.

### Shared CSS

- `assets/css/bagisto-theme.css` is the extracted storefront stylesheet.
- `assets/css/port-fixes.css` contains narrowly scoped compatibility rules.

Compatibility rules should remain minimal. New CSS should only be added when the captured stylesheet lacks a required utility or when cleaning removed a dependency that must be restored.

## 5. Recommended Django structure

The future Django project should treat the captures as source templates rather than mockups.

A reasonable structure is:

```text
templates/
  store/
    base.html
    home.html
    category.html
    product_detail.html
    customer/
      login.html
      register.html
      profile.html
    partials/
      header.html
      mobile_navigation.html
      search_drawer.html
      cart_drawer.html
      account_drawer.html
      service_strip.html
      footer.html
      product_card.html
```

This structure is only an organizational recommendation. It must not become an excuse to rewrite the visual components.

## 6. Parameterization strategy

Conversion should be mechanical.

Example:

```html
<h3>Demo Product</h3>
<img src="demo.webp" alt="Demo Product">
<span>$299.00</span>
```

becomes:

```django
<h3>{{ product.name }}</h3>
<img src="{{ product.primary_image_url }}" alt="{{ product.name }}">
<span>{{ product.display_price }}</span>
```

Repeated captured cards become a loop around the same markup:

```django
{% for product in products %}
    <!-- Existing product-card markup, parameterized only -->
{% endfor %}
```

Links should be converted to Django URL tags once the URL names are known. Static CSS, JavaScript, fonts, and placeholder assets should use `{% static %}`.

## 7. Data contracts

The exact Django model structure is intentionally deferred.

Before parameterization begins, define a small rendering contract for each page. These contracts can be backed by fixtures, dictionaries, serializers, or real QuerySets.

Minimum useful contracts:

### Product listing item

- Name
- URL or slug
- Primary image URL and alt text
- Current display price
- Optional old/compare price
- Stock state
- Optional badge or discount label

### Product detail

- Product identity and text
- Image collection
- Price information
- Availability
- Quantity constraints
- Options/variants, when applicable
- Related products

### Category page

- Category title and description
- Products
- Active filters
- Sort state
- Pagination state

### Store shell

- Navigation categories
- Customer authentication state
- Cart summary and items
- Wishlist/comparison counts, when available
- Theme preference handled client-side

The templates should not be coupled prematurely to uncertain model field names. Adapter properties, selectors, or view-context builders can provide stable rendering names.

## 8. Seed-first integration

The first Django milestone should render the preserved pages using seeded data.

Recommended order:

1. Create or connect the Django project.
2. Copy static assets into Django static directories.
3. Convert the shared shell and one representative page.
4. Define simple context contracts.
5. Add fixture data or a `seed_store` management command.
6. Confirm visual parity on desktop and mobile.
7. Convert the remaining pages.
8. Implement live cart, wishlist, filters, authentication, and checkout later.

This avoids blocking visual integration on unfinished commerce logic.

## 9. Captured states available

The repository currently provides references for:

- Anonymous and logged-in shell states
- Search drawer
- Cart drawer
- Open authenticated Account drawer
- Mobile bottom navigation
- Category/product listing presentation
- Multiple product-detail layouts
- Registration form and country listbox
- Customer profile/account layout
- Light and dark theme states

Transient states should continue to be captured visibly open before cleaning whenever their internal markup is needed.

## 10. Known limitations

- Clean captures do not retain the original React application behavior.
- Some destination URLs remain tied to the source site until Django URL names are defined.
- Search, cart, account, filters, and forms are currently preview behaviors or static references, not production backend integrations.
- The customer login capture may still need to be added if it is not present when work resumes.
- Browser testing remains necessary for responsive behavior and interactive parity.

## 11. Resume point

When development resumes, do not begin by recreating product cards, filters, galleries, or navigation.

Begin with:

1. Identify the target Django repository and app.
2. Agree on minimal page context/data contracts.
3. Move the existing static assets into Django.
4. Convert the shared shell from the captured markup.
5. Parameterize one page with fixture data.
6. Compare its output visually against the corresponding preview.

The captures and previews in this repository should remain available throughout the Django work as regression references.
