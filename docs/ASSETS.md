# Product Assets

PriceBridge stores visual assets (logos, product images) separately from `ProductModel` rows in the `ProductAsset` model. This keeps the data model clean and avoids assuming every model has a logo.

## Logo Fallback Strategy

When selecting an asset for display, use this priority:

1. **Active primary `model_logo`** -- exact model logo matched from Commons
2. **Active primary `series_logo`** -- series-level logo fallback
3. **Active `brand_logo`** -- brand-level logo fallback
4. **Placeholder** -- generic placeholder asset

If no `ProductAsset` exists for a model, the UI should display a placeholder or omit the image entirely. Missing logos are normal and should never block analysis or the dashboard.

## Syncing from Wikimedia Commons

The `sync_commons_assets` command searches Wikimedia Commons for model/series logos using the MediaWiki API. It does **not** use browser scraping.

### Run a full sync

```bash
python manage.py sync_commons_assets
```

### Dry-run (search without saving)

```bash
python manage.py sync_commons_assets --dry-run
```

### Process one model

```bash
python manage.py sync_commons_assets --model-id 42 --dry-run
```

### Filter by brand

```bash
python manage.py sync_commons_assets --brand Samsung --dry-run
```

### Re-check models with existing assets

```bash
python manage.py sync_commons_assets --force
```

### Save weak matches for manual review

```bash
python manage.py sync_commons_assets --save-weak --min-score 50
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--limit N` | 0 (all) | Process at most N models |
| `--model-id ID` | - | Process one model by ID |
| `--brand BRAND` | - | Filter by brand name |
| `--dry-run` | False | Search/rank without saving |
| `--force` | False | Re-check models that already have assets |
| `--min-score` | 70 | Minimum score to auto-save |
| `--save-weak` | False | Save weak matches as `manual_review` |
| `--asset-type` | `model_logo` | Asset type to assign |
| `--sleep` | 0.5 | Delay between API calls (seconds) |
| `--verbose` | False | Detailed per-model output |

## Inspecting Manual Review Matches

Assets with `match_status=manual_review` can be reviewed in Django admin:

- Go to **Market > Product Assets**
- Filter by **Match status: Manual review**
- Set `is_primary=True` and `is_active=True` for approved assets
- Set `is_active=False` to reject

## Legal Note

Many device logos on Wikimedia Commons are:
- **Public domain** for copyright purposes (simple wordmarks, geometric logos)
- **Trademarked** by their respective companies

Internal dashboard use within PriceBridge is generally fine. Public redistribution or commercial use of trademarked logos requires separate legal review. Always preserve license, attribution, and restriction metadata from Commons.

## Asset Metadata

Each `ProductAsset` stores:
- Commons title, file URL, and page URL
- Local downloaded file path
- MIME type, dimensions, file size
- License short name, license URL, usage terms
- Attribution, artist, credit
- Restrictions (e.g. "trademarked")
- Search query used to find the file
- Match score and status
- Raw metadata JSON for debugging
