import json
import types
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Avg, Count, F, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation
from django.views.decorators.http import require_http_methods

from market.models import (
    Brand,
    Condition,
    Country,
    DeviceVariant,
    InstagramPost,
    MarketListing,
    MarketListingSuggestion,
    OCRResult,
    OpportunitySnapshot,
    ProductModel,
    Source,
    SourceType,
    SupplierPrice,
)
from market.services.currency import convert_to_eur
from market.services.listing_suggestions import apply_listing_suggestion


@require_http_methods(["POST", "GET"])
def set_language(request):
    """Switch the active language and redirect back."""
    next_url = request.POST.get("next") or request.GET.get("next") or "/"
    lang = request.POST.get("language") or request.GET.get("language")
    if lang and lang in {"en", "tr"}:
        translation.activate(lang)
        request.session["django_language"] = lang
    return redirect(next_url)


def pct(value):
    if value is None:
        return ""
    return f"{value:.1f}%"


def money(value, suffix="EUR"):
    if value is None:
        return ""
    return f"{value:,.2f} {suffix}"


def money_amount(value, suffix):
    if value is None:
        return ""
    return f"{Decimal(str(value)):,.2f} {suffix}"


def converted_price_lines(price_eur, original_currency=""):
    if price_eur is None:
        return []
    eur = Decimal(str(price_eur))
    values = {
        "EUR": eur,
        "USD": eur * Decimal(str(settings.EUR_USD)),
        "TRY": eur * Decimal(str(settings.EUR_TRY)),
        "DZD": eur * Decimal(str(settings.DZD_PER_EUR_BLACK)),
    }
    original_currency = (original_currency or "").upper()
    return [
        {
            "currency": currency,
            "value": money_amount(value, currency),
            "is_original": False,
        }
        for currency, value in values.items()
        if currency != original_currency
    ]


def listing_image_url(listing):
    path = (getattr(listing, "image_path", "") or "").strip()
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    media_root = Path(settings.MEDIA_ROOT).resolve()
    try:
        rel_path = Path(path).resolve().relative_to(media_root)
        return f"{settings.MEDIA_URL}{rel_path.as_posix()}"
    except (OSError, ValueError):
        if path.startswith(str(settings.MEDIA_URL)):
            return path
        return ""


def admin_json_error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def parse_inline_decimal(value):
    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid number.") from exc


def parse_inline_int(value, allow_blank=True):
    text = str(value).strip()
    if not text:
        if allow_blank:
            return None
        raise ValueError("This field cannot be blank.")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError("Enter a valid integer.") from exc


def parse_inline_text(value, max_length=None, blank=True):
    text = str(value).strip()
    if not text and not blank:
        raise ValueError("This field cannot be blank.")
    if max_length and len(text) > max_length:
        raise ValueError(f"Text is too long. Max length is {max_length}.")
    return text


def parse_inline_choice(value, choices, blank=False):
    text = str(value).strip()
    if not text and blank:
        return ""
    valid_values = {choice[0] for choice in choices}
    if text not in valid_values:
        raise ValueError(f"Use one of: {', '.join(sorted(valid_values))}.")
    return text


def parse_inline_fk(value, model, blank=True):
    pk = parse_inline_int(value, allow_blank=blank)
    if pk is None:
        return None
    try:
        return model.objects.get(pk=pk)
    except model.DoesNotExist as exc:
        raise ValueError(f"{model.__name__} {pk} does not exist.") from exc


def parse_inline_storage(value):
    storage = parse_inline_int(value)
    if storage is None:
        return None
    valid_values = {choice[0] for choice in DeviceVariant.Storage.choices}
    if storage not in valid_values:
        raise ValueError(f"Use one of: {', '.join(str(item) for item in sorted(valid_values))}.")
    return storage


INLINE_MODELS = {
    "market-listings": {
        "model": MarketListing,
        "fields": {
            "title_raw": lambda value: parse_inline_text(value, max_length=300),
            "description_raw": lambda value: str(value).strip(),
            "price_original": parse_inline_decimal,
            "currency_original": lambda value: parse_inline_choice(value, MarketListing.Currency.choices),
            "condition": lambda value: parse_inline_choice(value, Condition.choices),
            "review_status": lambda value: parse_inline_choice(value, MarketListing.ReviewStatus.choices),
            "product_model": lambda value: parse_inline_fk(value, ProductModel),
            "variant": lambda value: parse_inline_fk(value, DeviceVariant),
            "storage_gb": parse_inline_storage,
            "battery_health": lambda value: parse_inline_int(value),
            "battery_cycles": lambda value: parse_inline_int(value),
            "sim_config": lambda value: parse_inline_text(value, max_length=80),
            "box_status": lambda value: parse_inline_text(value, max_length=120),
            "listing_url": lambda value: parse_inline_text(value, max_length=200),
        },
    },
    "product-models": {
        "model": ProductModel,
        "fields": {
            "canonical_name": lambda value: parse_inline_text(value, max_length=180, blank=False),
            "release_year": lambda value: parse_inline_int(value),
            "notes": lambda value: str(value).strip(),
        },
    },
    "device-variants": {
        "model": DeviceVariant,
        "fields": {
            "product_model": lambda value: parse_inline_fk(value, ProductModel, blank=False),
            "storage_gb": parse_inline_storage,
            "color": lambda value: parse_inline_text(value, max_length=80),
            "sim_config": lambda value: parse_inline_text(value, max_length=80),
            "region": lambda value: parse_inline_text(value, max_length=80),
            "canonical_label": lambda value: parse_inline_text(value, max_length=220, blank=False),
        },
    },
}


@require_http_methods(["PATCH", "DELETE"])
def inline_edit_api(request, model_key):
    if not (request.user.is_authenticated and request.user.is_staff):
        return admin_json_error("Staff login required.", status=403)

    config = INLINE_MODELS.get(model_key)
    if not config:
        return admin_json_error("Unknown editable model.", status=404)

    object_id = request.GET.get("id")
    if not object_id:
        return admin_json_error("Missing object id.")

    model = config["model"]
    obj = get_object_or_404(model, pk=object_id)

    if request.method == "DELETE":
        if model is not MarketListing:
            return admin_json_error("Only listings can be deleted from the frontend.", status=405)
        deleted_id = obj.pk
        obj.delete()
        return JsonResponse({"ok": True, "deleted": True, "id": deleted_id})

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return admin_json_error("Invalid JSON body.")

    field_name = payload.get("field")
    if field_name not in config["fields"]:
        return admin_json_error("This field is not editable.")

    try:
        parsed_value = config["fields"][field_name](payload.get("value", ""))
        setattr(obj, field_name, parsed_value)
        if isinstance(obj, MarketListing) and field_name in {"price_original", "currency_original"}:
            obj.price_eur = convert_to_eur(obj.price_original, obj.currency_original)
        obj.full_clean(exclude=None)
        obj.save()
    except (ValueError, ValidationError) as exc:
        message = exc.messages[0] if hasattr(exc, "messages") else str(exc)
        return admin_json_error(message)
    except IntegrityError:
        return admin_json_error("That edit conflicts with an existing database row.")

    display_value = getattr(obj, field_name)
    if hasattr(display_value, "pk"):
        display_value = str(display_value)
    elif display_value is None:
        display_value = ""
    else:
        display_value = str(display_value)

    return JsonResponse(
        {
            "ok": True,
            "id": obj.pk,
            "field": field_name,
            "value": display_value,
            "label": str(obj),
            "price_eur": str(obj.price_eur) if isinstance(obj, MarketListing) and obj.price_eur else "",
        }
    )


@require_http_methods(["POST"])
def listing_bulk_api(request):
    if not (request.user.is_authenticated and request.user.is_staff):
        return admin_json_error("Staff login required.", status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return admin_json_error("Invalid JSON body.")

    ids = payload.get("ids") or []
    if not isinstance(ids, list):
        return admin_json_error("ids must be a list.")
    try:
        ids = [int(item) for item in ids]
    except (TypeError, ValueError):
        return admin_json_error("ids must contain only listing ids.")
    ids = list(dict.fromkeys(ids))
    if not ids:
        return admin_json_error("Select at least one listing.")
    if len(ids) > 500:
        return admin_json_error("Bulk actions are limited to 500 listings at a time.")

    action = str(payload.get("action") or "").strip()
    qs = MarketListing.objects.filter(id__in=ids)

    if action == "assign_storage":
        try:
            storage_gb = parse_inline_storage(payload.get("storage_gb", ""))
        except ValueError as exc:
            return admin_json_error(str(exc))
        updated = qs.update(storage_gb=storage_gb)
        return JsonResponse({"ok": True, "action": action, "updated": updated})

    if action == "delete":
        selected_count = qs.count()
        deleted, _details = qs.delete()
        return JsonResponse({"ok": True, "action": action, "deleted": selected_count, "cascade_deleted": deleted})

    if action == "apply_suggestions":
        suggestions = (
            MarketListingSuggestion.objects.select_related("listing", "suggested_product_model")
            .filter(listing_id__in=ids, status=MarketListingSuggestion.Status.PENDING)
            .order_by("listing_id", "-created_at")
        )
        seen = set()
        applied = 0
        for suggestion in suggestions:
            if suggestion.listing_id in seen:
                continue
            seen.add(suggestion.listing_id)
            apply_listing_suggestion(suggestion)
            applied += 1
        return JsonResponse({"ok": True, "action": action, "updated": applied})

    if action == "reject_suggestions":
        updated = (
            MarketListingSuggestion.objects.filter(
                listing_id__in=ids,
                status=MarketListingSuggestion.Status.PENDING,
            ).update(status=MarketListingSuggestion.Status.REJECTED)
        )
        return JsonResponse({"ok": True, "action": action, "updated": updated})

    return admin_json_error("Unknown bulk action.")


def representative_listing(product_model, storage_gb=None, country=None, sim_config=""):
    qs = MarketListing.objects.filter(product_model=product_model).exclude(image_path="")
    if storage_gb:
        qs = qs.filter(storage_gb=storage_gb)
    if country:
        qs = qs.filter(country=country)
    return qs.order_by("price_eur", "-observed_at").first()


def rec_class(value):
    return {
        "buy": "rec-buy",
        "watch": "rec-watch",
        "ignore": "rec-ignore",
        "insufficient_data": "rec-insufficient",
    }.get(value, "rec-insufficient")


def review_class(value):
    return {
        MarketListing.ReviewStatus.AUTO: "verified",
        MarketListing.ReviewStatus.APPROVED: "verified",
        MarketListing.ReviewStatus.NEEDS_REVIEW: "review",
        MarketListing.ReviewStatus.REJECTED: "excluded",
    }.get(value, "excluded")


def source_code(value):
    return {
        SourceType.INSTAGRAM: "IG",
        SourceType.OUEDKNISS: "OK",
        SourceType.SAHIBINDEN: "SH",
        SourceType.SUPPLIER: "SL",
        SourceType.MANUAL: "MN",
    }.get(value, value[:2].upper())


def source_badge(value):
    return {
        SourceType.INSTAGRAM: "ig",
        SourceType.OUEDKNISS: "ok",
        SourceType.SAHIBINDEN: "sh",
        SourceType.SUPPLIER: "sl",
    }.get(value, "")


def coverage_counts(product_model, storage_gb, sim_config=""):
    listing_filter = {
        "product_model": product_model,
        "review_status__in": [MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
        "price_eur__isnull": False,
    }
    supplier_filter = {
        "product_model": product_model,
        "active": True,
        "supplier_price_eur__isnull": False,
    }
    if storage_gb:
        listing_filter["storage_gb"] = storage_gb
        supplier_filter["storage_gb"] = storage_gb
    else:
        listing_filter["storage_gb__isnull"] = True
        supplier_filter["storage_gb__isnull"] = True

    rows = (
        MarketListing.objects.filter(**listing_filter)
        .values("source_type")
        .annotate(count=Count("id"))
        .order_by("source_type")
    )
    coverage = [
        {
            "code": source_code(row["source_type"]),
            "class": source_badge(row["source_type"]),
            "count": row["count"],
        }
        for row in rows
    ]
    supplier_count = SupplierPrice.objects.filter(**supplier_filter).count()
    if supplier_count:
        coverage.append(
            {
                "code": source_code(SourceType.SUPPLIER),
                "class": source_badge(SourceType.SUPPLIER),
                "count": supplier_count,
            }
        )
    order = {"IG": 1, "OK": 2, "SH": 3, "SL": 4}
    return sorted(coverage, key=lambda item: order.get(item["code"], 99))


def base_context(active):
    return {"active": active}


def listing_display_rows(listings):
    rows = []
    for item in listings:
        rows.append(
            {
                "item": item,
                "is_supplier": False,
                "source_code": source_code(item.source_type),
                "source_name": item.source.name,
                "country_label": item.get_country_display(),
                "review_class": review_class(item.review_status),
                "review_label": item.get_review_status_display(),
                "title": item.title_raw or "-",
                "product_label": str(item.product_model) if item.product_model else "-",
                "variant_label": str(item.variant) if item.variant else "-",
                "storage_gb": item.storage_gb,
                "sim_config": item.sim_config,
                "price": f"{item.price_original or ''} {item.currency_original}".strip(),
                "original_price": item.price_original,
                "original_currency": item.currency_original,
                "eur": money(item.price_eur),
                "converted_prices": converted_price_lines(item.price_eur, item.currency_original),
                "condition_label": item.get_condition_display(),
                "observed_at": item.observed_at,
                "image_url": listing_image_url(item),
            }
        )
    return rows


def supplier_display_rows(supplier_prices):
    rows = []
    for item in supplier_prices:
        rows.append(
            {
                "item": item,
                "is_supplier": True,
                "source_code": source_code(SourceType.SUPPLIER),
                "source_name": item.source.name,
                "country_label": item.source.get_country_display(),
                "review_class": "verified" if item.active else "excluded",
                "review_label": "Active" if item.active else "Inactive",
                "title": item.raw_text,
                "product_label": str(item.product_model) if item.product_model else "-",
                "variant_label": str(item.variant) if item.variant else "-",
                "storage_gb": item.storage_gb,
                "sim_config": item.sim_config,
                "price": f"{item.supplier_price_usd or ''} USD".strip(),
                "original_price": item.supplier_price_usd,
                "original_currency": "USD",
                "eur": money(item.supplier_price_eur),
                "converted_prices": converted_price_lines(item.supplier_price_eur, "USD"),
                "condition_label": item.get_condition_display(),
                "observed_at": item.created_at,
                "image_url": "",
            }
        )
    return rows


def data_quality_issues(item):
    issues = []
    if item.review_status == MarketListing.ReviewStatus.NEEDS_REVIEW:
        issues.append({"label": "needs review", "class": "badge-warn"})
    if not item.product_model_id:
        issues.append({"label": "missing model", "class": "badge-warn"})
    if item.product_model_id and not item.storage_gb:
        issues.append({"label": "missing storage", "class": "badge-warn"})
    if item.price_original is None or item.price_eur is None:
        issues.append({"label": "missing price", "class": "badge-warn"})
    if not item.image_path:
        issues.append({"label": "no image", "class": ""})
    if item.review_status == MarketListing.ReviewStatus.REJECTED:
        issues.append({"label": "rejected", "class": "excluded"})
    return issues or [{"label": "ok", "class": "badge-ok"}]


def suggestion_display(suggestion):
    if not suggestion:
        return None
    return {
        "item": suggestion,
        "product_label": str(suggestion.suggested_product_model) if suggestion.suggested_product_model else "-",
        "storage_label": f"{suggestion.suggested_storage_gb}GB" if suggestion.suggested_storage_gb else "-",
        "sim_label": suggestion.suggested_sim_config or "default",
        "condition_label": (
            Condition(suggestion.suggested_condition).label if suggestion.suggested_condition else "-"
        ),
        "confidence_percent": round((suggestion.confidence or 0) * 100),
        "confidence_class": "badge-ok" if suggestion.confidence >= 0.75 else "badge-warn",
        "reason": suggestion.reason,
    }


def build_opportunity_rows(opportunities, tab):
    rows = []
    for item in opportunities:
        storage = item.storage_gb
        gain_split = item.gain_split() if hasattr(item, "gain_split") else None
        if tab == "supplier" and item.supplier_margin_percent is not None:
            active_margin = item.supplier_margin_percent
            active_gross = item.gross_margin_vs_supplier_eur
        else:
            active_margin = item.margin_percent
            active_gross = item.gross_margin_vs_sahibinden_eur
        cat_obj = getattr(item.product_model, 'category', None)
        rows.append(
            {
                "item": item,
                "brand": item.product_model.brand.name if item.product_model.brand else "Unknown",
                "category_name": cat_obj.name if cat_obj else "",
                "category_slug": cat_obj.slug if cat_obj else "",
                "image_url": listing_image_url(
                    representative_listing(item.product_model, storage, country=Country.ALGERIA)
                    or representative_listing(item.product_model, storage, country=Country.TURKIYE)
                    or item
                ),
                "recommendation_class": rec_class(item.recommendation),
                "margin_class": "good" if active_margin and active_margin > 15 else "warn",
                "margin_percent": pct(active_margin),
                "algeria_min": money(item.algeria_min_eur),
                "algeria_avg": money(item.algeria_avg_eur),
                "turkiye_avg": money(item.sahibinden_avg_eur),
                "gross_margin": money(active_gross),
                "gain_split": gain_split,
                "my_gain": money(gain_split["my_gain_eur"]) if gain_split else "",
                "buyer_price": money(gain_split["offer_price_to_buyer_eur"]) if gain_split else "",
                "buyer_gain": money(gain_split["buyer_gain_eur"]) if gain_split else "",
                "buyer_gain_percent": pct(gain_split["buyer_gain_percent"]) if gain_split else "",
                "supplier": money(item.supplier_eur),
                "supplier_margin": pct(item.supplier_margin_percent),
                "sahibinden_margin": pct(item.margin_percent),
                "sources": coverage_counts(item.product_model, storage),
                "gross_value": active_gross,
            }
        )
    return rows


OPP_SOURCE_TABS = {
    "all": "All",
    "algeria": "Algeria",
    "supplier": "Supplier",
}

ALGERIA_SOURCE_TYPES = [SourceType.INSTAGRAM, SourceType.OUEDKNISS]

CAT_TABS = {
    "all": "All",
    "phones": "Phones",
    "laptops": "Laptops",
    "non-phones": "Other",
}

STORAGE_OPTIONS = {
    "": "Any",
    "64": "64 GB",
    "128": "128 GB",
    "256": "256 GB",
    "512": "512 GB",
    "1024": "1 TB",
    "2048": "2 TB",
}

_APPROVED = [MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED]


def _compute_source_rows(algeria_source_types, rec_filter, min_confidence, min_margin, sort, limit=300,
                         cat=None, brand=None, q=None, storage=None):
    """Compute opportunity rows using Algeria listings from one or more source types."""
    from decimal import Decimal
    from django.db.models import Avg, Min

    if not isinstance(algeria_source_types, (list, tuple)):
        algeria_source_types = [algeria_source_types]

    specs_qs = MarketListing.objects.filter(
        country=Country.ALGERIA,
        source_type__in=algeria_source_types,
        review_status__in=_APPROVED,
        price_eur__isnull=False,
        product_model__isnull=False,
    )
    if cat and cat in CAT_TABS and cat != "all":
        specs_qs = specs_qs.filter(product_model__category__slug=cat)
    if brand:
        specs_qs = specs_qs.filter(product_model__brand__name__iexact=brand)
    if q:
        specs_qs = specs_qs.filter(product_model__canonical_name__icontains=q)
    if storage:
        specs_qs = specs_qs.filter(storage_gb=storage)

    specs = list(specs_qs.values("product_model_id", "storage_gb").distinct())

    rows = []
    for spec in specs:
        pm_id = spec["product_model_id"]
        storage_gb = spec["storage_gb"]
        try:
            pm = ProductModel.objects.get(id=pm_id)
        except ProductModel.DoesNotExist:
            continue

        algeria = MarketListing.objects.filter(
            product_model_id=pm_id, country=Country.ALGERIA, source_type__in=algeria_source_types,
            review_status__in=_APPROVED, price_eur__isnull=False,
        )
        sahibinden = MarketListing.objects.filter(
            product_model_id=pm_id, country=Country.TURKIYE, source_type=SourceType.SAHIBINDEN,
            review_status__in=_APPROVED, price_eur__isnull=False,
        )
        if storage_gb:
            algeria = algeria.filter(storage_gb=storage_gb)
            sahibinden = sahibinden.filter(storage_gb=storage_gb)
        else:
            algeria = algeria.filter(storage_gb__isnull=True)
            sahibinden = sahibinden.filter(storage_gb__isnull=True)

        a = algeria.aggregate(min_price=Min("price_eur"), avg_price=Avg("price_eur"))
        s = sahibinden.aggregate(avg_price=Avg("price_eur"))
        algeria_min = a["min_price"]
        algeria_avg = a["avg_price"]
        sahibinden_avg = s["avg_price"]
        if not algeria_min or not sahibinden_avg:
            continue

        margin = Decimal(str(sahibinden_avg)) - Decimal(str(algeria_min))
        margin_pct = float((margin / Decimal(str(algeria_min))) * 100)

        if margin_pct > 15:
            rec = OpportunitySnapshot.Recommendation.BUY
        elif margin_pct > 5:
            rec = OpportunitySnapshot.Recommendation.WATCH
        else:
            rec = OpportunitySnapshot.Recommendation.IGNORE

        algeria_count = algeria.count()
        sahibinden_count = sahibinden.count()
        confidence = int(min(algeria_count * 12 + sahibinden_count * 8 + (15 if storage_gb else 0) + 5, 100))

        if rec_filter is not None and rec not in rec_filter:
            continue
        if min_confidence and confidence < min_confidence:
            continue
        if min_margin and margin_pct < min_margin:
            continue

        item = types.SimpleNamespace()
        item.id = 0
        item.product_model = pm
        item.storage_gb = storage_gb
        item.sim_config = ""
        item.confidence_score = confidence
        item.recommendation = rec
        item.get_recommendation_display = lambda r=rec: OpportunitySnapshot.Recommendation(r).label
        item.created_at = None

        rows.append({
            "item": item,
            "is_source_row": True,
            "brand": pm.brand.name if pm.brand else "Unknown",
            "image_url": listing_image_url(
                representative_listing(pm, storage_gb, country=Country.ALGERIA)
                or representative_listing(pm, storage_gb, country=Country.TURKIYE)
            ),
            "recommendation_class": rec_class(rec),
            "margin_class": "good" if margin_pct > 15 else "warn",
            "margin_percent": pct(margin_pct),
            "algeria_min": money(algeria_min),
            "algeria_avg": money(algeria_avg),
            "turkiye_avg": money(sahibinden_avg),
            "gross_margin": money(margin),
            "supplier": "",
            "supplier_margin": "",
            "sahibinden_margin": pct(margin_pct),
            "sources": coverage_counts(pm, storage_gb),
            "gross_value": margin,
        })

    sort_key = {
        "margin": lambda r: float(r["margin_percent"].rstrip("%")) if r["margin_percent"] else -999,
        "confidence": lambda r: r["item"].confidence_score or 0,
        "updated": lambda r: 0,
    }.get(sort, lambda r: float(r.get("gross_value") or 0))
    rows.sort(key=sort_key, reverse=True)
    return rows[:limit]


def _median(values):
    items = sorted(values)
    n = len(items)
    if not n:
        return None
    if n % 2:
        return items[n // 2]
    return (items[n // 2 - 1] + items[n // 2]) / 2


def opportunities(request):
    src = request.GET.get("src", "all")
    if src not in OPP_SOURCE_TABS:
        src = "all"

    cat = request.GET.get("cat", "all")
    if cat not in CAT_TABS:
        cat = "all"
    brand = request.GET.get("brand", "").strip()
    q = request.GET.get("q", "").strip()

    if src == "supplier":
        qs = OpportunitySnapshot.objects.select_related(
            "product_model", "product_model__brand", "variant",
        ).exclude(supplier_eur__isnull=True)
        total = qs.count()
        if cat and cat != "all":
            qs = qs.filter(product_model__category__slug=cat)
        if brand:
            qs = qs.filter(product_model__brand__name__iexact=brand)
        if q:
            qs = qs.filter(product_model__canonical_name__icontains=q)
        qs = qs.order_by(
            F("gross_margin_vs_supplier_eur").desc(nulls_last=True),
            F("supplier_margin_percent").desc(nulls_last=True),
        )
        filtered = list(qs[:300])
        rows = build_opportunity_rows(filtered, tab="supplier")
        margins = [item.supplier_margin_percent for item in filtered if item.supplier_margin_percent is not None]
        confidences = [item.confidence_score for item in filtered if item.confidence_score is not None]
        grosses = [
            float(item.gross_margin_vs_supplier_eur)
            for item in filtered if item.gross_margin_vs_supplier_eur is not None
        ]
        total_all = OpportunitySnapshot.objects.count()
    elif src == "algeria":
        rows = _compute_source_rows(
            ALGERIA_SOURCE_TYPES,
            None, 0, 0, "gross", limit=300,
            cat=cat, brand=brand, q=q,
        )
        margins = [
            float(r["margin_percent"].rstrip("%")) for r in rows
            if r.get("margin_percent")
        ]
        confidences = [r["item"].confidence_score for r in rows if r["item"].confidence_score]
        grosses = [float(r.get("gross_value") or 0) for r in rows]
        total = len(rows)
        total_all = OpportunitySnapshot.objects.count()
    else:
        qs = OpportunitySnapshot.objects.select_related(
            "product_model", "product_model__brand", "variant",
        )
        total = qs.count()
        total_all = total
        if cat and cat != "all":
            qs = qs.filter(product_model__category__slug=cat)
        if brand:
            qs = qs.filter(product_model__brand__name__iexact=brand)
        if q:
            qs = qs.filter(product_model__canonical_name__icontains=q)
        qs = qs.order_by(
            F("gross_margin_vs_sahibinden_eur").desc(nulls_last=True),
            F("margin_percent").desc(nulls_last=True),
        )
        filtered = list(qs[:300])
        rows = build_opportunity_rows(filtered, tab="sahibinden")
        margins = [item.margin_percent for item in filtered if item.margin_percent is not None]
        confidences = [item.confidence_score for item in filtered if item.confidence_score is not None]
        grosses = [
            float(item.gross_margin_vs_sahibinden_eur)
            for item in filtered if item.gross_margin_vs_sahibinden_eur is not None
        ]

    counts = {
        "total": total_all,
        "visible": len(rows),
    }

    brands_with_data = (
        Brand.objects.filter(
            productmodel__opportunitysnapshot__isnull=False,
        )
        .distinct()
        .order_by("name")
    )

    buy_count = len([r for r in rows if r["item"].recommendation == OpportunitySnapshot.Recommendation.BUY])
    watch_count = len([r for r in rows if r["item"].recommendation == OpportunitySnapshot.Recommendation.WATCH])
    ignore_count = len([r for r in rows if r["item"].recommendation == OpportunitySnapshot.Recommendation.IGNORE])
    best_row = max(rows, key=lambda r: float(r.get("gross_value") or 0)) if rows else None

    return render(
        request,
        "market/opportunities.html",
        base_context("opportunities")
        | {
            "rows": rows,
            "source_tabs": OPP_SOURCE_TABS,
            "active_src": src,
            "cat_tabs": CAT_TABS,
            "active_cat": cat,
            "brand_list": [{"name": b.name} for b in brands_with_data],
            "active_brand": brand,
            "search_query": q,
            "counts": counts,
            "signal_stats": [
                {"label": "Visible", "value": f"{counts['visible']} / {counts['total']}", "delta": "matching filters"},
                {"label": "Buy", "value": buy_count, "delta": "actionable", "color": "green"},
                {"label": "Watch", "value": watch_count, "delta": "monitor", "color": "amber"},
                {"label": "Ignore", "value": ignore_count, "delta": "pass", "color": "slate"},
                {"label": "Median margin", "value": pct(_median(margins)), "delta": "filtered"},
                {"label": "Total gross", "value": money(sum(grosses)), "delta": "if all actioned"},
            ],
            "best_opportunity": best_row,
        },
    )


def opportunity_detail(request, pk):
    opportunity = get_object_or_404(
        OpportunitySnapshot.objects.select_related("product_model", "product_model__brand", "product_model__category", "variant"),
        pk=pk,
    )
    storage = opportunity.storage_gb
    listing_filter = {"product_model": opportunity.product_model}
    if storage:
        listing_filter["storage_gb"] = storage
    else:
        listing_filter["storage_gb__isnull"] = True

    algeria_listings = (
        MarketListing.objects.select_related("source", "product_model", "variant")
        .filter(country=Country.ALGERIA, **listing_filter)
        .order_by("price_eur", "-observed_at")
    )
    turkiye_listings = (
        MarketListing.objects.select_related("source", "product_model", "variant")
        .filter(country=Country.TURKIYE, **listing_filter)
        .order_by("price_eur", "-observed_at")
    )

    cat_obj = opportunity.product_model.category
    supplier_margin = pct(opportunity.supplier_margin_percent) if opportunity.supplier_margin_percent else ""
    gain_split = opportunity.gain_split()

    all_algeria_storages = sorted(
        s for s in MarketListing.objects.filter(
            product_model=opportunity.product_model, country=Country.ALGERIA,
            review_status__in=_APPROVED, price_eur__isnull=False,
        ).values_list("storage_gb", flat=True).distinct() if s is not None
    )
    all_turkiye_storages = sorted(
        s for s in MarketListing.objects.filter(
            product_model=opportunity.product_model, country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            review_status__in=_APPROVED, price_eur__isnull=False,
        ).values_list("storage_gb", flat=True).distinct() if s is not None
    )

    return render(
        request,
        "market/opportunity_detail.html",
        base_context("opportunities")
        | {
            "opportunity": opportunity,
            "brand": opportunity.product_model.brand.name if opportunity.product_model.brand else "Unknown",
            "category_name": cat_obj.name if cat_obj else "",
            "category_slug": cat_obj.slug if cat_obj else "",
            "storage": storage,
            "recommendation_class": rec_class(opportunity.recommendation),
            "margin_percent": pct(opportunity.margin_percent),
            "algeria_min": money(opportunity.algeria_min_eur),
            "algeria_avg": money(opportunity.algeria_avg_eur),
            "turkiye_avg": money(opportunity.sahibinden_avg_eur),
            "gross_margin": money(opportunity.gross_margin_vs_sahibinden_eur),
            "gain_split": gain_split,
            "my_gain": money(gain_split["my_gain_eur"]) if gain_split else "",
            "my_gain_dzd": money_amount(gain_split["my_gain_dzd"], "DZD") if gain_split else "",
            "buyer_price": money(gain_split["offer_price_to_buyer_eur"]) if gain_split else "",
            "buyer_price_dzd": money_amount(gain_split["offer_price_to_buyer_dzd"], "DZD") if gain_split else "",
            "buyer_gain": money(gain_split["buyer_gain_eur"]) if gain_split else "",
            "buyer_gain_percent": pct(gain_split["buyer_gain_percent"]) if gain_split else "",
            "my_gain_percent_of_gross": pct(gain_split["my_gain_percent_of_gross"]) if gain_split else "",
            "supplier": money(opportunity.supplier_eur),
            "supplier_margin": supplier_margin,
            "coverage": coverage_counts(opportunity.product_model, storage),
            "hero_image_url": listing_image_url(
                representative_listing(opportunity.product_model, storage, country=Country.ALGERIA)
                or representative_listing(opportunity.product_model, storage, country=Country.TURKIYE)
                or opportunity
            ),
            "algeria_rows": listing_display_rows(algeria_listings),
            "turkiye_rows": listing_display_rows(turkiye_listings),
            "is_cross_storage": storage is None,
            "all_algeria_storages": all_algeria_storages,
            "all_turkiye_storages": all_turkiye_storages,
        },
    )


@staff_member_required
def listings(request):
    listings_qs = MarketListing.objects.select_related("source", "product_model", "variant").order_by("-observed_at")
    supplier_qs = SupplierPrice.objects.select_related("source", "product_model", "variant").order_by("-created_at")
    search = request.GET.get("q", "").strip()
    source_type = request.GET.get("source_type", "")
    country = request.GET.get("country", "")
    review_status = request.GET.get("review_status", "")

    if search:
        listings_qs = listings_qs.filter(
            Q(title_raw__icontains=search)
            | Q(description_raw__icontains=search)
            | Q(product_model__canonical_name__icontains=search)
            | Q(variant__canonical_label__icontains=search)
        )
        supplier_qs = supplier_qs.filter(
            Q(raw_text__icontains=search)
            | Q(product_model__canonical_name__icontains=search)
            | Q(variant__canonical_label__icontains=search)
        )
    if source_type:
        listings_qs = listings_qs.filter(source_type=source_type)
        if source_type != SourceType.SUPPLIER:
            supplier_qs = supplier_qs.none()
    else:
        supplier_qs = supplier_qs
    if country:
        listings_qs = listings_qs.filter(country=country)
        supplier_qs = supplier_qs.filter(source__country=country)
    if review_status:
        listings_qs = listings_qs.filter(review_status=review_status)
        if review_status in {MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED}:
            supplier_qs = supplier_qs.filter(active=True)
        elif review_status == MarketListing.ReviewStatus.REJECTED:
            supplier_qs = supplier_qs.filter(active=False)
        else:
            supplier_qs = supplier_qs.none()

    listing_rows = listing_display_rows(listings_qs[:300]) + supplier_display_rows(supplier_qs[:300])
    listing_rows = sorted(
        listing_rows,
        key=lambda row: row["observed_at"],
        reverse=True,
    )[:300]

    return render(
        request,
        "market/listings.html",
        base_context("listings")
        | {
            "listing_rows": listing_rows,
            "filters": {
                "q": search,
                "source_type": source_type,
                "country": country,
                "review_status": review_status,
            },
            "source_types": SourceType.choices,
            "countries": Country.choices,
            "conditions": Condition.choices,
            "review_statuses": MarketListing.ReviewStatus.choices,
        },
    )


@staff_member_required
def data_quality(request):
    approved = [MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED]
    source_quality = []
    for row in (
        MarketListing.objects.values("source_type", "country")
        .annotate(
            total=Count("id"),
            usable=Count("id", filter=Q(review_status__in=approved, price_eur__isnull=False)),
            review=Count("id", filter=Q(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW)),
        )
        .order_by("source_type", "country")
    ):
        source_quality.append(row)

    duplicate_variant_groups = (
        DeviceVariant.objects.values("product_model_id", "identity_key").annotate(c=Count("id")).filter(c__gt=1).count()
    )
    unmatched = MarketListing.objects.filter(product_model__isnull=True).count()
    missing_variant = MarketListing.objects.filter(product_model__isnull=False, storage_gb__isnull=True).count()

    review_search = request.GET.get("q", "").strip()
    review_source_type = request.GET.get("source_type", "")
    review_country = request.GET.get("country", "")
    review_status = request.GET.get("review_status", MarketListing.ReviewStatus.NEEDS_REVIEW)
    review_issue = request.GET.get("issue", "")

    review_qs = MarketListing.objects.select_related("source", "product_model", "variant").order_by("-observed_at")
    if review_search:
        review_qs = review_qs.filter(
            Q(title_raw__icontains=review_search)
            | Q(description_raw__icontains=review_search)
            | Q(product_model__canonical_name__icontains=review_search)
            | Q(variant__canonical_label__icontains=review_search)
        )
    if review_source_type:
        review_qs = review_qs.filter(source_type=review_source_type)
    if review_country:
        review_qs = review_qs.filter(country=review_country)
    if review_status:
        review_qs = review_qs.filter(review_status=review_status)
    if review_issue == "missing_model":
        review_qs = review_qs.filter(product_model__isnull=True)
    elif review_issue == "missing_variant":
        review_qs = review_qs.filter(product_model__isnull=False, storage_gb__isnull=True)
    elif review_issue == "missing_price":
        review_qs = review_qs.filter(Q(price_original__isnull=True) | Q(price_eur__isnull=True))
    elif review_issue == "no_image":
        review_qs = review_qs.filter(image_path="")

    review_rows = listing_display_rows(review_qs[:120])
    latest_suggestions = {}
    if review_rows:
        row_ids = [row["item"].id for row in review_rows]
        pending_suggestions = (
            MarketListingSuggestion.objects.select_related("suggested_product_model")
            .filter(listing_id__in=row_ids, status=MarketListingSuggestion.Status.PENDING)
            .order_by("listing_id", "-created_at")
        )
        for suggestion in pending_suggestions:
            latest_suggestions.setdefault(suggestion.listing_id, suggestion)
    for row in review_rows:
        row["issues"] = data_quality_issues(row["item"])
        row["suggestion"] = suggestion_display(latest_suggestions.get(row["item"].id))

    return render(
        request,
        "market/data_quality.html",
        base_context("data_quality")
        | {
            "source_quality": source_quality,
            "review_rows": review_rows,
            "review_filters": {
                "q": review_search,
                "source_type": review_source_type,
                "country": review_country,
                "review_status": review_status,
                "issue": review_issue,
            },
            "review_issue_choices": [
                ("", "All issues"),
                ("missing_model", "Missing model"),
                ("missing_variant", "Missing storage"),
                ("missing_price", "Missing price"),
                ("no_image", "No image"),
            ],
            "source_types": SourceType.choices,
            "countries": Country.choices,
            "conditions": Condition.choices,
            "review_statuses": MarketListing.ReviewStatus.choices,
            "storage_choices": DeviceVariant.Storage.choices,
            "metrics": {
                "instagram_posts": InstagramPost.objects.count(),
                "ocr_pending": OCRResult.objects.filter(status=OCRResult.Status.PENDING).count(),
                "ocr_failed": OCRResult.objects.filter(status=OCRResult.Status.FAILED).count(),
                "unmatched": unmatched,
                "missing_variant": missing_variant,
                "models_without_variants": ProductModel.objects.filter(devicevariant__isnull=True).count(),
                "duplicate_variant_groups": duplicate_variant_groups,
                "supplier_prices": SupplierPrice.objects.count(),
                "snapshots": OpportunitySnapshot.objects.count(),
                "pending_suggestions": MarketListingSuggestion.objects.filter(
                    status=MarketListingSuggestion.Status.PENDING
                ).count(),
            },
        },
    )


@staff_member_required
def sources(request):
    source_rows = []
    for source in Source.objects.order_by("source_type", "name"):
        listings = MarketListing.objects.filter(source=source)
        supplier_prices = SupplierPrice.objects.filter(source=source)
        source_rows.append(
            {
                "source": source,
                "code": source_code(source.source_type),
                "total": listings.count() or supplier_prices.count(),
                "usable": listings.filter(
                    review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
                    price_eur__isnull=False,
                ).count()
                or supplier_prices.filter(active=True).count(),
                "review": listings.filter(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW).count(),
                "last_seen": listings.aggregate(value=Max("observed_at"))["value"]
                or supplier_prices.aggregate(value=Max("created_at"))["value"],
            }
        )

    return render(
        request,
        "market/sources.html",
        base_context("sources") | {"source_rows": source_rows},
    )
