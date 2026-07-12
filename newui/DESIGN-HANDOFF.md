# PriceBridge — Design Handoff

## Product Overview

PriceBridge is a private wholesale electronics sourcing platform for Turkish shop owners. It helps buyers identify profitable import opportunities from Algeria to Türkiye by showing delivered-to-shop cost, resale range, and expected profit for each device.

## Target User

- **Primary persona:** Turkish electronics shop owner browsing on mobile
- **Context:** Wholesale purchasing decisions, budget-conscious, needs fast scanning
- **Language:** Turkish (prototype in English for now)

## Design Principles

1. **Price hierarchy first** — "Delivered to your shop" is the most prominent number
2. **Buyer-friendly language** — No technical jargon (no "Clean snapshot", "Gross spread", etc.)
3. **Professional wholesale feel** — Not an analytics dashboard, not a consumer marketplace
4. **Fast scanning** — Large touch targets, clear condition badges, compact spacing
5. **Trust signals** — Verified badges, seller ratings, IMEI status visible

## Color System

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| `--pb-bg` | `#f1f5f9` | `#0f172a` | Page background |
| `--pb-surface` | `#ffffff` | `#1e293b` | Cards, modals |
| `--pb-fg` | `#0f172a` | `#f1f5f9` | Primary text |
| `--pb-fg2` | `#334155` | `#cbd5e1` | Secondary text |
| `--pb-muted` | `#64748b` | `#94a3b8` | Captions, metadata |
| `--pb-border` | `#e2e8f0` | `#334155` | Borders, dividers |
| `--pb-accent` | `#2563eb` | `#3b82f6` | Primary action, links |

## Status Colors

| Status | Light | Dark | Usage |
|--------|-------|------|-------|
| Success | `#059669` / `#d1fae5` | `#10b981` / `#064e3b` | Verified, profitable |
| Warning | `#d97706` / `#fef3c7` | `#f59e0b` / `#78350f` | Needs attention |
| Danger | `#dc2626` / `#fee2e2` | `#ef4444` / `#7f1d1d` | Risk, errors |

## Typography

- **Font family:** Inter (system fallback: system-ui, sans-serif)
- **Scale:** text-xs (11px), text-sm (13px), text-base (15px), text-lg (17px), text-xl (20px), text-2xl (24px), text-3xl (30px)
- **Weights:** 400 (body), 500 (labels), 600 (emphasis), 700 (headings), 800 (screen titles)
- **Tabular numerics:** Prices and numbers use font-variant-numeric: tabular-nums

## Spacing

- 8pt base grid
- Component padding: 16px (p-4)
- Card gap: 12px–16px
- Section gap: 20px–24px
- Border radius: 8px (small), 12px (medium), 16px (large), 24px (cards)

## Component Inventory

### DeviceCard
- Product image (16:9 aspect ratio, object-contain)
- Condition badge (top-left) + Trust badge
- Heart/save button (top-right)
- Model name + storage + color
- Feature chips: Battery %, Box included, Full set
- **Delivered to your shop** price (largest number, bold)
- Resale range + Expected profit (side by side)
- Details + Add to Plan buttons

### BudgetBar
- Total / Used / Remaining breakdown
- Progress bar with color states (blue → amber → red)
- Editable budget with inline editing

### CategoryChips
- Horizontal scrollable chip row
- Active state: filled accent color
- Inactive: outlined with border

### BottomSheet
- Modal overlay with slide-up animation
- Used for: Sort, Filter, and other option pickers
- Handle area at top for dismiss

### ConditionBadge
- Color-coded: Grade A+ (green), Grade A (blue), Grade A- (indigo), Grade B+ (amber)
- Border + tinted background

### TrustBadge
- Verified (green), High (blue), Standard (gray)
- Shield icon prefix

## Screen Specifications

### Screen 1: Deals Feed
- Sticky header with title + filter/sort buttons
- Budget summary bar
- Category chips (All, iPhone, Samsung, Xiaomi, Laptops, Consoles)
- Device card list
- Sort options: Highest profit, Lowest cost, Newest, Highest resale
- Filter options: Trust level, Min profit, Max cost

### Screen 2: Device Detail
- Sticky header with back + save + copy
- Swipeable image gallery (touch support)
- Device identity + condition badges
- Price hero: Delivered cost, Resale range, Profit, Quick sale, Sale time
- Expandable cost breakdown (6 line items)
- iPhone condition checklist (11 items with check/warning)
- Listing source with seller info
- Sticky bottom CTA: Add to Purchase Plan

### Screen 3: Purchase Plan
- Budget overview with progress bar
- 4-metric grid: Devices, Total cost, Resale, Profit
- Device list with remove/details actions
- Confirm + Export actions

### Screen 4: Budget Optimizer
- Budget input field
- 7 strategy options with descriptions
- Constraint inputs: Max devices, Max per model, Min battery, Max cost, Min profit
- Generate plan button with loading state
- Result: Recommended basket with explanation

### Screen 5: Search
- Search input with icon
- Recent searches list
- Suggested model chips
- Grouped results by brand
- Same DeviceCard component

### Screen 6: Saved Devices
- Saved device list with checkbox selection
- Compare button (2–4 devices)
- Comparison modal with table layout
- Remove from saved + Add to plan actions

### Account Screen (bonus)
- User profile card
- Settings list (notifications, shipping, payment, sign out)

## Interactions

| Interaction | Trigger | Effect |
|-------------|---------|--------|
| Dark mode | Sun/Moon icon in top bar | Toggles html.dark class |
| Role switch | Buyer/Internal dropdown | Shows/hides internal fields |
| Budget edit | Edit button on BudgetBar | Inline number input |
| Category filter | Tap chip | Filters device list |
| Sort | Filter icon → BottomSheet | Sorts device list |
| Filter | Settings icon → BottomSheet | Filters by trust, profit, cost |
| Save/Unsave | Heart icon on card | Toggles saved state |
| Add to Plan | "+ Plan" button | Toggles plan state |
| Device detail | "Details" button | Navigates to detail screen |
| Image gallery | Swipe left/right | Cycles through images |
| Cost breakdown | Tap header | Expands/collapses |
| Search | Type in search input | Filters devices in real-time |
| Compare | Check 2–4 devices → Compare | Opens comparison modal |
| Plan quantity | +/- buttons in plan | Adjusts device count |
| Remove from plan | Remove button | Removes device from plan |

## Responsive Breakpoints

- **Primary mobile:** 390px (iPhone 14/15 Pro)
- **Small mobile:** 360px (Samsung Galaxy S)
- **Large mobile:** 430px (iPhone 14/15 Pro Max)
- **Tablet:** 768px+
- **Desktop:** 1024px+

Max container width: 480px (centered on larger screens)

## Accessibility Notes

- All interactive elements have 44px minimum touch targets
- Color contrast meets WCAG AA (4.5:1 for text)
- Focus states visible on all buttons and inputs
- Screen reader labels on icon buttons
- Semantic HTML structure (nav, main, section)

## Animation & Motion

- Slide-up animation for bottom sheets (300ms, ease-out)
- Fade-in for content changes (200ms)
- Scale-in for modals (200ms, ease-out)
- Progress bar transitions (500ms)
- Hover states on all interactive elements (150ms)

## Dark Mode

- Toggled via sun/moon icon in top bar
- Persisted during session (not localStorage in prototype)
- All tokens swap via CSS custom properties
- Status colors adapt for dark backgrounds
- Borders and shadows reduce intensity

## Role System

### Buyer Mode (default)
- Shows: Delivered cost, Resale range, Expected profit, Trust level, Condition
- Hides: Raw Algeria purchase cost, Platform margin, Internal profit share, Parser confidence, Database IDs, Review workflow, Internal notes

### Internal Mode
- Shows all buyer fields PLUS collapsed "Management" section
- Management section includes: DB ID, Source, Seller details, Risk level
- Internal controls never dominate the buyer experience

## File Structure

```
pricebridge-prototype/
├── index.html          ← Main React app (all screens)
├── mockData.js         ← Device data, categories, budget
├── DESIGN-HANDOFF.md   ← This file
└── API-CONTRACT.md     ← Django endpoint specs
```

## Future Considerations

- Turkish language translation for all UI text
- Real product images (replace placeholder CDN URLs)
- Backend integration (Django REST API)
- Push notifications for price drops
- Offline support for cached listings
- Multi-currency display (TRY + EUR + DZD)
- Barcode scanning for in-store verification
