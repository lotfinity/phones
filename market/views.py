import json
import logging
import sys
import types
from io import StringIO
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Avg, Count, F, Max, Q
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from market.services.brand_logos import brand_initial as _brand_initial
from market.services.brand_logos import brand_logo_url as _brand_logo_url
from market.services.gain_split import compute_gain_split

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
from market.services.currency import (
    convert_to_eur,
    eur_rate_or_setting,
    eur_to_dzd,
    eur_to_try,
    eur_to_usd,
    eur_try_rate,
    eur_usd_rate,
    usd_try_rate,
)
from market.services.listing_suggestions import apply_listing_suggestion


@require_http_methods(["POST", "GET"])
def set_language(request):
    """Switch the active language and redirect back."""
    next_url = request.POST.get("next") or request.GET.get("next") or "/"
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = "/"
    lang = request.POST.get("language") or request.GET.get("language")
    response = redirect(next_url)
    supported_languages = {code for code, _name in settings.LANGUAGES}
    if lang in supported_languages and translation.check_for_language(lang):
        translation.activate(lang)
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            lang,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            path=settings.LANGUAGE_COOKIE_PATH,
            domain=settings.LANGUAGE_COOKIE_DOMAIN,
            secure=settings.LANGUAGE_COOKIE_SECURE,
            httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
            samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        )
    return response


def pct(value):
    if value is None:
        return ""
    return f"{value:.1f}%"


def ratio_pct(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return ""
    numerator = Decimal(str(numerator))
    denominator = Decimal(str(denominator))
    if denominator == 0:
        return ""
    return pct((numerator / denominator) * Decimal("100"))


def money(value, suffix="EUR"):
    if value is None:
        return ""

    if suffix is None:
        suffix = "EUR"
    currency = suffix.upper()
    amount = Decimal(str(value))
    if currency == "EUR":
        return f"{amount:,.2f} EUR"
    if currency == "USD":
        return f"{eur_to_usd(amount):,.2f} USD"
    if currency == "TRY":
        return f"{eur_to_try(amount):,.2f} TRY"
    if currency == "DZD":
        return f"{eur_to_dzd(amount):,.2f} DZD"
    return f"{amount:,.2f} {suffix}"


def money_amount(value, suffix):
    if value is None:
        return ""
    return f"{Decimal(str(value)):,.2f} {suffix}"


def get_active_currency(request):
    supported = {code for code in ["EUR", "USD", "TRY", "DZD"]}
    currency = request.GET.get("currency") or request.COOKIES.get("pricebridge_currency")
    if currency:
        currency = str(currency).upper()
        if currency in supported:
            return currency
    return "EUR"


def current_fx_rates():
    def rate(value):
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return [
        {"label": "€1", "value": f"₺{rate(eur_try_rate()):,.2f}"},
        {"label": "$1", "value": f"₺{rate(usd_try_rate()):,.2f}"},
        {"label": "€1", "value": f"{rate(eur_rate_or_setting('DZD', 'DZD_PER_EUR_BLACK')):,.2f} DZD"},
        {"label": "€1", "value": f"${rate(eur_usd_rate()):,.2f}"},
    ]


def fx_converter_payload():
    from market.models import CurrencyRate

    rates = {
        "EUR": Decimal("1"),
        "USD": eur_usd_rate(),
        "TRY": eur_try_rate(),
        "DZD": eur_rate_or_setting("DZD", "DZD_PER_EUR_BLACK"),
    }
    latest_rows = list(CurrencyRate.objects.order_by("-observed_at", "-id")[:8])
    latest_observed = latest_rows[0].observed_at.isoformat() if latest_rows else ""

    def fmt(value):
        return str(Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))

    return {
        "base": "EUR",
        "rates": {currency: fmt(value) for currency, value in rates.items()},
        "latest_observed": latest_observed,
        "rows": [
            {
                "pair": f"{row.base_currency}/{row.quote_currency}",
                "rate": fmt(row.rate),
                "source": row.source,
                "observed_at": row.observed_at.isoformat(),
            }
            for row in latest_rows
        ],
    }


def converted_price_lines(price_eur, original_currency=""):
    if price_eur is None:
        return []
    eur = Decimal(str(price_eur))
    values = {
        "EUR": eur,
        "USD": eur_to_usd(eur),
        "TRY": eur_to_try(eur),
        "DZD": eur_to_dzd(eur),
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


def base_context(request, active):
    return {
        "active": active,
        "selected_currency": get_active_currency(request),
        "fx_rates": current_fx_rates(),
        "currency_options": [
            ("EUR", "EUR"),
            ("USD", "USD"),
            ("TRY", "TRY"),
            ("DZD", "DZD"),
        ],
    }


def set_currency(request):
    next_url = request.POST.get("next") or request.GET.get("next") or "/"
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = "/"
    currency = (request.POST.get("currency") or request.GET.get("currency") or "EUR").upper()
    supported_currencies = {code for code, _ in [("EUR", "EUR"), ("USD", "USD"), ("TRY", "TRY"), ("DZD", "DZD")]}
    response = redirect(next_url)
    if currency in supported_currencies:
        response.set_cookie(
            "pricebridge_currency",
            currency,
            max_age=60 * 60 * 24 * 365,
            path="/",
            secure=settings.SESSION_COOKIE_SECURE,
            httponly=False,
            samesite=getattr(settings, "SESSION_COOKIE_SAMESITE", "Lax"),
        )
    return response


def listing_display_rows(listings):
    rows = []
    for item in listings:
        category_slug = item.product_model.category.slug if item.product_model and item.product_model.category else ""
        brand_name = item.product_model.brand.name if item.product_model and item.product_model.brand else ""
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
                "spec_label": "RAM" if category_slug == "laptops" else "Storage",
                "sim_config": item.sim_config,
                "price": f"{item.price_original or ''} {item.currency_original}".strip(),
                "original_price": item.price_original,
                "original_currency": item.currency_original,
                "eur": money(item.price_eur),
                "eur_raw": float(item.price_eur) if item.price_eur is not None else None,
                "converted_prices": converted_price_lines(item.price_eur, item.currency_original),
                "condition_label": item.get_condition_display(),
                "observed_at": item.observed_at,
                "image_url": listing_image_url(item),
                "brand": brand_name or "Unknown",
                "brand_logo_url": _brand_logo_url(brand_name),
                "brand_initial": _brand_initial(brand_name or item.title_raw),
            }
        )
    return rows


def supplier_display_rows(supplier_prices):
    rows = []
    for item in supplier_prices:
        brand_name = item.product_model.brand.name if item.product_model and item.product_model.brand else ""
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
                "eur_raw": float(item.supplier_price_eur) if item.supplier_price_eur is not None else None,
                "converted_prices": converted_price_lines(item.supplier_price_eur, "USD"),
                "condition_label": item.get_condition_display(),
                "observed_at": item.created_at,
                "image_url": "",
                "brand": brand_name or "Unknown",
                "brand_logo_url": _brand_logo_url(brand_name),
                "brand_initial": _brand_initial(brand_name or item.raw_text),
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


def can_view_internal_gain(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_superuser)


def build_opportunity_rows(opportunities, tab, selected_currency="EUR", show_internal_gain=False):
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
        brand_name = item.product_model.brand.name if item.product_model.brand else "Unknown"
        rows.append(
            {
                "item": item,
                "brand": brand_name,
                "brand_logo_url": _brand_logo_url(brand_name),
                "brand_initial": _brand_initial(brand_name),
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
                "algeria_min": money(item.algeria_min_eur, selected_currency),
                "algeria_avg": money(item.algeria_avg_eur, selected_currency),
                "turkiye_avg": money(item.sahibinden_avg_eur, selected_currency),
                "gross_margin": money(active_gross, selected_currency),
                "capital_roi": ratio_pct(active_gross, item.algeria_min_eur),
                "gain_split": gain_split,
                "my_gain": money(gain_split["my_gain_eur"], selected_currency) if gain_split and show_internal_gain else "",
                "buyer_price": money(gain_split["offer_price_to_buyer_eur"], selected_currency) if gain_split else "",
                "buyer_gain": money(gain_split["buyer_gain_eur"], selected_currency) if gain_split else "",
                "buyer_gain_percent": pct(gain_split["buyer_gain_percent"]) if gain_split else "",
                "supplier": money(item.supplier_eur),
                "supplier_usd": f"{eur_to_usd(item.supplier_eur):,.0f} USD" if item.supplier_eur is not None else "",
                "supplier_margin": pct(item.supplier_margin_percent),
                "sahibinden_margin": pct(item.margin_percent),
                "algeria_min_dzd": f"{eur_to_dzd(item.algeria_min_eur):,.0f} DZD" if item.algeria_min_eur is not None else "",
                "turkiye_avg_try": f"{eur_to_try(item.sahibinden_avg_eur):,.0f} TRY" if item.sahibinden_avg_eur is not None else "",
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
            "brand_logo_url": _brand_logo_url(pm.brand.name if pm.brand else ""),
            "brand_initial": _brand_initial(pm.brand.name if pm.brand else pm.canonical_name),
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
    show_internal_gain = can_view_internal_gain(request)
    selected_currency = get_active_currency(request)
    src = request.GET.get("src", "all")
    if src not in OPP_SOURCE_TABS:
        src = "all"
    if not show_internal_gain and src != "all":
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
        rows = build_opportunity_rows(filtered, tab="supplier", selected_currency=selected_currency, show_internal_gain=show_internal_gain)
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
        rows = build_opportunity_rows(filtered, tab="sahibinden", selected_currency=selected_currency, show_internal_gain=show_internal_gain)
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
    strong_count = len([r for r in rows if r.get("gain_split") and r["gain_split"]["deal_quality"] == "strong"])
    medium_count = len([r for r in rows if r.get("gain_split") and r["gain_split"]["deal_quality"] == "medium"])
    weak_count = len([r for r in rows if r.get("gain_split") and r["gain_split"]["deal_quality"] == "weak"])
    best_row = max(rows, key=lambda r: float(r.get("gross_value") or 0)) if rows else None
    signal_stats = [
        {"label": "Visible", "value": f"{counts['visible']} / {counts['total']}", "delta": "matching filters"},
        {"label": "Buy", "value": buy_count, "delta": "actionable", "color": "green"},
        {"label": "Watch", "value": watch_count, "delta": "monitor", "color": "amber"},
        {"label": "Ignore", "value": ignore_count, "delta": "pass", "color": "slate"},
        {"label": "Median margin", "value": pct(_median(margins)), "delta": "filtered"},
        {"label": "Total gross", "value": money(sum(grosses), selected_currency), "delta": "if all actioned"},
    ]
    if not show_internal_gain:
        signal_stats = [
            {"label": "Visible", "value": f"{counts['visible']}", "delta": "matching filters"},
            {"label": "Strong", "value": strong_count, "delta": "buyer gain", "color": "green"},
            {"label": "Medium", "value": medium_count, "delta": "buyer gain", "color": "amber"},
            {"label": "Weak", "value": weak_count, "delta": "thin gain", "color": "slate"},
        ]

    return render(
        request,
        "market/opportunities.html",
        base_context(request, "opportunities")
        | {
            "rows": rows,
            "source_tabs": OPP_SOURCE_TABS if show_internal_gain else {"all": "All"},
            "active_src": src,
            "cat_tabs": CAT_TABS,
            "active_cat": cat,
            "brand_list": [{"name": b.name} for b in brands_with_data],
            "active_brand": brand,
            "search_query": q,
            "can_view_internal_gain": show_internal_gain,
            "counts": counts,
            "signal_stats": signal_stats,
            "best_opportunity": best_row,
        },
    )


def opportunity_detail(request, pk):
    show_internal_gain = can_view_internal_gain(request)
    selected_currency = get_active_currency(request)
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
    is_laptop = bool(cat_obj and cat_obj.slug == "laptops")
    supplier_margin = pct(opportunity.supplier_margin_percent) if opportunity.supplier_margin_percent else ""
    gain_split = opportunity.gain_split()

    if is_laptop and storage is None:
        algeria_listings = (
            MarketListing.objects.select_related("source", "product_model", "variant")
            .filter(country=Country.ALGERIA, product_model=opportunity.product_model)
            .order_by("price_eur", "-observed_at")
        )
        turkiye_listings = (
            MarketListing.objects.select_related("source", "product_model", "variant")
            .filter(country=Country.TURKIYE, product_model=opportunity.product_model)
            .order_by("price_eur", "-observed_at")
        )

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
        base_context(request, "opportunities")
        | {
            "opportunity": opportunity,
            "brand": opportunity.product_model.brand.name if opportunity.product_model.brand else "Unknown",
            "category_name": cat_obj.name if cat_obj else "",
            "category_slug": cat_obj.slug if cat_obj else "",
            "storage": storage,
            "spec_label": "RAM" if is_laptop else "Storage",
            "recommendation_class": rec_class(opportunity.recommendation),
            "margin_percent": pct(opportunity.margin_percent),
            "algeria_min": money(opportunity.algeria_min_eur, selected_currency),
            "algeria_avg": money(opportunity.algeria_avg_eur, selected_currency),
            "turkiye_avg": money(opportunity.sahibinden_avg_eur, selected_currency),
            "gross_margin": money(opportunity.gross_margin_vs_sahibinden_eur, selected_currency),
            "capital_roi": ratio_pct(opportunity.gross_margin_vs_sahibinden_eur, opportunity.algeria_min_eur),
            "gain_split": gain_split,
            "my_gain": money(gain_split["my_gain_eur"], selected_currency) if gain_split and show_internal_gain else "",
            "my_gain_dzd": money_amount(gain_split["my_gain_dzd"], "DZD") if gain_split and show_internal_gain else "",
            "buyer_price": money(gain_split["offer_price_to_buyer_eur"], selected_currency) if gain_split else "",
            "buyer_price_dzd": money_amount(gain_split["offer_price_to_buyer_dzd"], "DZD") if gain_split else "",
            "buyer_gain": money(gain_split["buyer_gain_eur"], selected_currency) if gain_split else "",
            "buyer_gain_percent": pct(gain_split["buyer_gain_percent"]) if gain_split else "",
            "my_gain_percent_of_gross": (
                pct(gain_split["my_gain_percent_of_gross"]) if gain_split and show_internal_gain else ""
            ),
            "supplier": money(opportunity.supplier_eur, selected_currency),
            "supplier_margin": supplier_margin,
            "coverage": coverage_counts(opportunity.product_model, storage),
            "hero_image_url": listing_image_url(
                representative_listing(opportunity.product_model, storage, country=Country.ALGERIA)
                or representative_listing(opportunity.product_model, storage, country=Country.TURKIYE)
                or opportunity
            ),
            "algeria_rows": listing_display_rows(algeria_listings),
            "turkiye_rows": listing_display_rows(turkiye_listings),
            "can_view_internal_gain": show_internal_gain,
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
        base_context(request, "listings")
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
        base_context(request, "data_quality")
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
        base_context(request, "sources") | {"source_rows": source_rows},
    )


DEALS_PAGE_SIZE = 10


def _compute_all_deals():
    """Compute all deals grouped by brand, sorted by margin descending."""
    import statistics
    from market import services as market_services
    from market.models import SupplierPrice

    algeria_listings = (
        MarketListing.objects.select_related("source", "product_model", "product_model__brand", "variant")
        .filter(
            country=Country.ALGERIA,
            review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
            price_eur__isnull=False,
            product_model__isnull=False,
        )
        .order_by("product_model__brand__name", "product_model__canonical_name", "storage_gb", "price_eur")
    )

    brand_deals = {}
    for listing in algeria_listings:
        pm = listing.product_model
        brand = pm.brand.name if pm.brand else "Unknown"
        storage = listing.storage_gb

        sah_query = MarketListing.objects.filter(
            source_type=SourceType.SAHIBINDEN,
            product_model=pm,
            price_eur__isnull=False,
            review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
        )
        if storage:
            sah_query = sah_query.filter(storage_gb=storage)

        sah_prices_eur = list(sah_query.values_list("price_eur", flat=True))
        sah_prices_try = list(sah_query.values_list("price_original", flat=True))
        sah_count = len(sah_prices_eur)

        if not sah_count:
            continue

        sah_median_eur = statistics.median(sah_prices_eur)
        sah_median_try = statistics.median(sah_prices_try)
        sah_min_try = min(sah_prices_try)
        sah_max_try = max(sah_prices_try)
        sah_urls = list(sah_query.values_list("listing_url", flat=True)[:10])

        margin_eur = (sah_median_eur - listing.price_eur) if listing.price_eur else None
        margin_pct = (margin_eur / listing.price_eur * 100) if (margin_eur is not None and listing.price_eur) else None

        supplier = SupplierPrice.objects.filter(
            product_model=pm, active=True, supplier_price_usd__isnull=False,
        )
        if storage:
            supplier = supplier.filter(storage_gb=storage)
        supplier_first = supplier.first()

        # Compute FX-converted display prices using current rates
        try:
            from market.services import currency as fx
        except Exception:
            fx = None

        price_try = None
        price_usd = None
        price_dzd = None
        if listing.price_eur is not None and fx:
            try:
                price_try = fx.eur_to_try(listing.price_eur)
            except Exception:
                price_try = None
            try:
                price_usd = fx.eur_to_usd(listing.price_eur)
            except Exception:
                price_usd = None
            try:
                price_dzd = fx.eur_to_dzd(listing.price_eur)
            except Exception:
                price_dzd = None

        # Sahibinden median is stored in TRY; convert to EUR/USD/DZD
        sah_median_eur = None
        sah_median_usd = None
        sah_median_dzd = None
        if sah_median_try is not None and fx:
            try:
                sah_median_eur = fx.try_to_eur(sah_median_try)
                sah_median_usd = fx.eur_to_usd(sah_median_eur)
                sah_median_dzd = fx.eur_to_dzd(sah_median_eur)
            except Exception:
                sah_median_eur = sah_median_usd = sah_median_dzd = None

        # Supplier conversions (prefer supplier_eur if present)
        supplier_try = None
        supplier_dzd = None
        if supplier_first:
            try:
                if supplier_first.supplier_price_eur is not None and fx:
                    supplier_try = fx.eur_to_try(supplier_first.supplier_price_eur)
                    supplier_dzd = fx.eur_to_dzd(supplier_first.supplier_price_eur)
                elif supplier_first.supplier_price_usd is not None and fx:
                    sup_eur = fx.usd_to_eur(supplier_first.supplier_price_usd)
                    supplier_try = fx.eur_to_try(sup_eur)
                    supplier_dzd = fx.eur_to_dzd(sup_eur)
            except Exception:
                supplier_try = supplier_dzd = None

        deal = {
            "id": listing.id,
            "brand": brand,
            "model": pm.canonical_name,
            "brand_logo_url": _brand_logo_url(brand),
            "brand_initial": _brand_initial(brand),
            "storage_gb": storage,
            "title": listing.title_raw or f"{pm.canonical_name} {storage or ''}GB".strip(),
            "price_original": listing.price_original,
            "currency_original": listing.currency_original,
            "price_eur": listing.price_eur,
            "price_try": float(price_try) if price_try is not None else None,
            "price_usd": float(price_usd) if price_usd is not None else None,
            "price_dzd": float(price_dzd) if price_dzd is not None else None,
            "condition": listing.get_condition_display(),
            "source_code": source_code(listing.source_type),
            "source_name": listing.source.name,
            "image_url": listing_image_url(listing),
            "listing_url": listing.listing_url,
            "observed_at": listing.observed_at,
            "sah_median": sah_median_try,
            "sah_median_eur": float(sah_median_eur) if sah_median_eur is not None else None,
            "sah_median_usd": float(sah_median_usd) if sah_median_usd is not None else None,
            "sah_median_dzd": float(sah_median_dzd) if sah_median_dzd is not None else None,
            "sah_min": sah_min_try,
            "sah_max": sah_max_try,
            "sah_count": sah_count,
            "sah_urls": [u for u in sah_urls if u],
            "sah_urls_json": json.dumps([u for u in sah_urls if u]),
            "margin_eur": margin_eur,
            "margin_pct": margin_pct,
            "supplier_usd": float(supplier_first.supplier_price_usd) if supplier_first and supplier_first.supplier_price_usd is not None else None,
            "supplier_eur": float(supplier_first.supplier_price_eur) if supplier_first and supplier_first.supplier_price_eur is not None else None,
            "supplier_try": float(supplier_try) if supplier_try is not None else None,
            "supplier_dzd": float(supplier_dzd) if supplier_dzd is not None else None,
        }
        brand_deals.setdefault(brand, []).append(deal)

    brand_summaries = []
    for brand_name, deals in brand_deals.items():
        deals.sort(key=lambda d: d["margin_pct"] or -9999, reverse=True)
        margins = [d["margin_pct"] for d in deals if d["margin_pct"] is not None]
        avg_margin = sum(margins) / len(margins) if margins else 0
        brand_summaries.append({
            "brand": brand_name,
            "deal_count": len(deals),
            "avg_margin": avg_margin,
            "deals": deals,
        })

    brand_summaries.sort(key=lambda b: b["avg_margin"], reverse=True)

    all_deals = []
    for bs in brand_summaries:
        all_deals.extend(bs["deals"])
    all_deals.sort(key=lambda d: d["margin_pct"] or -9999, reverse=True)
    all_margins = [d["margin_pct"] for d in all_deals if d["margin_pct"] is not None]
    all_avg = sum(all_margins) / len(all_margins) if all_margins else 0
    brand_summaries.insert(0, {
        "brand": "ALL",
        "deal_count": len(all_deals),
        "avg_margin": all_avg,
        "deals": all_deals,
    })

    return brand_summaries


def _deal_to_json(d):
    """Convert a DealSnapshot instance or dict to JSON-safe dict."""
    from decimal import Decimal

    def _val(key, obj=d):
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)
    def _float(key, obj=d):
        v = _val(key, obj)
        if v is None:
            return None
        if isinstance(v, Decimal):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "id": _val("id"),
        "model": _val("model_name") or _val("model"),
        "brand": _val("brand_name") or _val("brand") or "",
        "brand_logo_url": _brand_logo_url(_val("brand_name") or _val("brand") or ""),
        "brand_initial": _brand_initial(_val("brand_name") or _val("brand") or _val("model_name") or _val("model") or ""),
        "storage_gb": _val("storage_gb"),
        "title": _val("title"),
        "price_original": _float("price_original"),
        "currency_original": _val("currency_original"),
        "price_eur": _float("price_eur"),
        "price_try": _float("price_try"),
        "price_usd": _float("price_usd"),
        "price_dzd": _float("price_dzd"),
        "sah_median": _float("sah_median"),
        "sah_count": _val("sah_count"),
        "sah_urls": _val("sah_urls"),
        "margin_pct": _float("margin_pct"),
        "buyer_price": _float("buyer_price"),
        "buyer_price_dzd": _float("buyer_price_dzd"),
        "buyer_gain": _float("buyer_gain"),
        "buyer_gain_percent": _float("buyer_gain_percent"),
        "my_gain": _float("my_gain"),
        "my_gain_dzd": _float("my_gain_dzd"),
        "my_gain_percent": _float("my_gain_percent"),
        "deal_quality": _val("deal_quality"),
        "supplier_usd": _float("supplier_usd"),
        "source_code": _val("source_code"),
        "source_name": _val("source_name"),
        "condition": _val("condition"),
        "condition_class": _val("condition_class"),
        "condition_label_tr": _val("condition_label_tr"),
        "image_url": _val("image_url"),
        "listing_url": _val("listing_url"),
        "observed_at": _val("observed_at").isoformat() if hasattr(_val("observed_at"), "isoformat") else _val("observed_at"),
    }


def _deal_gain_split_fields(*, algeria_min_eur, turkiye_avg_eur, gross_margin_eur, supplier_eur=None):
    gain_split = compute_gain_split(
        algeria_min_eur=algeria_min_eur,
        turkiye_avg_eur=turkiye_avg_eur,
        gross_margin_eur=gross_margin_eur,
        supplier_eur=supplier_eur,
    )
    if not gain_split:
        return {
            "gain_split": None,
            "buyer_price": None,
            "buyer_price_dzd": None,
            "buyer_gain": None,
            "buyer_gain_percent": None,
            "my_gain": None,
            "my_gain_dzd": None,
            "my_gain_percent": None,
            "deal_quality": "",
        }
    return {
        "gain_split": gain_split,
        "buyer_price": gain_split["offer_price_to_buyer_eur"],
        "buyer_price_dzd": gain_split["offer_price_to_buyer_dzd"],
        "buyer_gain": gain_split["buyer_gain_eur"],
        "buyer_gain_percent": gain_split["buyer_gain_percent"],
        "my_gain": gain_split["my_gain_eur"],
        "my_gain_dzd": gain_split["my_gain_dzd"],
        "my_gain_percent": gain_split["my_gain_percent_of_gross"],
        "deal_quality": gain_split["deal_quality"],
    }


def _snapshot_to_dict(snap):
    """Convert a DealSnapshot instance to a template-friendly dict."""
    audit = getattr(snap.listing, "condition_audit", None) if snap.listing_id else None
    gain_fields = _deal_gain_split_fields(
        algeria_min_eur=snap.price_eur,
        turkiye_avg_eur=snap.sah_median_eur,
        gross_margin_eur=snap.margin_eur,
        supplier_eur=snap.supplier_eur,
    )
    return {
        "id": snap.id,
        "brand": snap.brand_name,
        "model": snap.model_name,
        "brand_logo_url": _brand_logo_url(snap.brand_name),
        "brand_initial": _brand_initial(snap.brand_name),
        "storage_gb": snap.storage_gb,
        "title": snap.title,
        "price_original": snap.price_original,
        "currency_original": snap.currency_original,
        "price_eur": snap.price_eur,
        "price_try": snap.price_try,
        "price_usd": snap.price_usd,
        "price_dzd": snap.price_dzd,
        "condition": snap.condition,
        "condition_class": audit.condition_class if audit else "",
        "condition_label_tr": audit.condition_label_tr if audit else "",
        "source_code": snap.source_code,
        "source_name": snap.source_name,
        "image_url": snap.image_url,
        "listing_url": snap.listing_url,
        "observed_at": snap.observed_at,
        "sah_median": snap.sah_median,
        "sah_median_eur": snap.sah_median_eur,
        "sah_median_usd": snap.sah_median_usd,
        "sah_median_dzd": snap.sah_median_dzd,
        "sah_min": snap.sah_min,
        "sah_max": snap.sah_max,
        "sah_count": snap.sah_count,
        "sah_urls": snap.sah_urls,
        "sah_urls_json": snap.sah_urls_json,
        "margin_eur": snap.margin_eur,
        "margin_pct": snap.margin_pct,
        "supplier_usd": snap.supplier_usd,
        "supplier_eur": snap.supplier_eur,
        "supplier_try": snap.supplier_try,
        "supplier_dzd": snap.supplier_dzd,
        **gain_fields,
    }


def _clean_deal_dicts():
    from market.clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot

    deals = []
    phone_qs = PhoneOpportunitySnapshot.objects.filter(
        recommendation=PhoneOpportunitySnapshot.Recommendation.BUY,
    ).order_by("-gross_margin_eur", "-margin_percent")
    for snap in phone_qs:
        gain_fields = _deal_gain_split_fields(
            algeria_min_eur=snap.algeria_min_eur,
            turkiye_avg_eur=snap.turkiye_avg_eur,
            gross_margin_eur=snap.gross_margin_eur,
        )
        deals.append({
            "id": f"phone-{snap.pk}",
            "brand": snap.brand,
            "model": snap.model,
            "brand_logo_url": _brand_logo_url(snap.brand),
            "brand_initial": _brand_initial(snap.brand or snap.model),
            "storage_gb": snap.storage_gb,
            "title": f"{snap.brand} {snap.model}".strip(),
            "price_original": snap.algeria_min_eur,
            "currency_original": "EUR",
            "price_eur": snap.algeria_min_eur,
            "price_try": None,
            "price_usd": None,
            "price_dzd": None,
            "condition": "clean snapshot",
            "condition_class": "",
            "condition_label_tr": "",
            "source_code": "PHONE",
            "source_name": "PhoneListing v2",
            "image_url": "",
            "listing_url": (snap.algeria_urls or [""])[0],
            "observed_at": snap.generated_at,
            "sah_median": snap.turkiye_avg_eur,
            "sah_median_eur": snap.turkiye_avg_eur,
            "sah_median_usd": None,
            "sah_median_dzd": None,
            "sah_min": snap.turkiye_min_eur,
            "sah_max": snap.turkiye_avg_eur,
            "sah_count": snap.turkiye_count,
            "sah_urls": snap.turkiye_urls or [],
            "sah_urls_json": json.dumps(snap.turkiye_urls or []),
            "margin_eur": snap.gross_margin_eur,
            "margin_pct": snap.margin_percent,
            "supplier_usd": None,
            "supplier_eur": None,
            "supplier_try": None,
            "supplier_dzd": None,
            **gain_fields,
        })
    laptop_qs = LaptopOpportunitySnapshot.objects.filter(
        recommendation__in=[
            LaptopOpportunitySnapshot.Recommendation.BUY,
            LaptopOpportunitySnapshot.Recommendation.GOOD_OPPORTUNITY,
        ],
    ).order_by("-gross_margin_eur", "-margin_percent")
    for snap in laptop_qs:
        gain_fields = _deal_gain_split_fields(
            algeria_min_eur=snap.algeria_min_eur,
            turkiye_avg_eur=snap.turkiye_avg_eur,
            gross_margin_eur=snap.gross_margin_eur,
        )
        specs = " / ".join(
            part for part in [
                snap.cpu,
                snap.gpu,
                f"{snap.ram_gb}GB RAM" if snap.ram_gb else "",
                f"{snap.storage_gb}GB" if snap.storage_gb else "",
            ]
            if part
        )
        title = f"{snap.brand} {snap.model}".strip()
        if specs:
            title = f"{title} {specs}"
        deals.append({
            "id": f"laptop-{snap.pk}",
            "brand": snap.brand,
            "model": snap.model,
            "brand_logo_url": _brand_logo_url(snap.brand),
            "brand_initial": _brand_initial(snap.brand or snap.model),
            "storage_gb": snap.storage_gb,
            "title": title,
            "price_original": snap.algeria_min_eur,
            "currency_original": "EUR",
            "price_eur": snap.algeria_min_eur,
            "price_try": None,
            "price_usd": None,
            "price_dzd": None,
            "condition": "clean snapshot",
            "condition_class": "",
            "condition_label_tr": "",
            "source_code": "LAP",
            "source_name": "LaptopListing v2",
            "image_url": "",
            "listing_url": (snap.algeria_urls or [""])[0],
            "observed_at": snap.generated_at,
            "sah_median": snap.turkiye_avg_eur,
            "sah_median_eur": snap.turkiye_avg_eur,
            "sah_median_usd": None,
            "sah_median_dzd": None,
            "sah_min": snap.turkiye_min_eur,
            "sah_max": snap.turkiye_avg_eur,
            "sah_count": snap.turkiye_count,
            "sah_urls": snap.turkiye_urls or [],
            "sah_urls_json": json.dumps(snap.turkiye_urls or []),
            "margin_eur": snap.gross_margin_eur,
            "margin_pct": snap.margin_percent,
            "supplier_usd": None,
            "supplier_eur": None,
            "supplier_try": None,
            "supplier_dzd": None,
            **gain_fields,
        })
    console_qs = ConsoleOpportunitySnapshot.objects.filter(
        recommendation__in=[
            ConsoleOpportunitySnapshot.Recommendation.BUY,
            ConsoleOpportunitySnapshot.Recommendation.GOOD_OPPORTUNITY,
        ],
    ).order_by("-gross_margin_eur", "-margin_percent")
    for snap in console_qs:
        gain_fields = _deal_gain_split_fields(
            algeria_min_eur=snap.algeria_min_eur,
            turkiye_avg_eur=snap.turkiye_avg_eur,
            gross_margin_eur=snap.gross_margin_eur,
        )
        specs = " / ".join(
            part for part in [
                snap.chipset,
                f"{snap.ram_gb}GB RAM" if snap.ram_gb else "",
                f"{snap.storage_gb}GB" if snap.storage_gb else "",
            ]
            if part
        )
        title = f"{snap.brand} {snap.model}".strip()
        if specs:
            title = f"{title} {specs}"
        deals.append({
            "id": f"console-{snap.pk}",
            "brand": snap.brand,
            "model": snap.model,
            "brand_logo_url": _brand_logo_url(snap.brand),
            "brand_initial": _brand_initial(snap.brand or snap.model),
            "storage_gb": snap.storage_gb,
            "title": title,
            "price_original": snap.algeria_min_eur,
            "currency_original": "EUR",
            "price_eur": snap.algeria_min_eur,
            "price_try": None,
            "price_usd": None,
            "price_dzd": None,
            "condition": "clean snapshot",
            "condition_class": "",
            "condition_label_tr": "",
            "source_code": "CON",
            "source_name": "ConsoleListing v1",
            "image_url": "",
            "listing_url": (snap.algeria_urls or [""])[0],
            "observed_at": snap.generated_at,
            "sah_median": snap.turkiye_avg_eur,
            "sah_median_eur": snap.turkiye_avg_eur,
            "sah_median_usd": None,
            "sah_median_dzd": None,
            "sah_min": snap.turkiye_min_eur,
            "sah_max": snap.turkiye_avg_eur,
            "sah_count": snap.turkiye_count,
            "sah_urls": snap.turkiye_urls or [],
            "sah_urls_json": json.dumps(snap.turkiye_urls or []),
            "margin_eur": snap.gross_margin_eur,
            "margin_pct": snap.margin_percent,
            "supplier_usd": None,
            "supplier_eur": None,
            "supplier_try": None,
            "supplier_dzd": None,
            **gain_fields,
        })
    deals.sort(key=lambda item: (item["margin_eur"] or Decimal("0"), item["margin_pct"] or Decimal("0")), reverse=True)
    return deals


def _clean_deals_available():
    from market.clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot

    return (
        PhoneOpportunitySnapshot.objects.exists()
        or LaptopOpportunitySnapshot.objects.exists()
        or ConsoleOpportunitySnapshot.objects.exists()
    )


def _clean_brand_summaries():
    deals = _clean_deal_dicts()
    grouped = {}
    for deal in deals:
        grouped.setdefault(deal["brand"], []).append(deal)

    brand_summaries = []
    for brand, brand_deals in grouped.items():
        margins = [d["margin_pct"] for d in brand_deals if d["margin_pct"] is not None]
        avg_margin = sum(margins) / len(margins) if margins else Decimal("0")
        brand_summaries.append({
            "brand": brand,
            "deal_count": len(brand_deals),
            "avg_margin": avg_margin,
            "deals": brand_deals[:DEALS_PAGE_SIZE],
            "deal_count_total": len(brand_deals),
        })
    brand_summaries.sort(key=lambda item: item["avg_margin"] or Decimal("0"), reverse=True)

    all_margins = [d["margin_pct"] for d in deals if d["margin_pct"] is not None]
    all_avg = sum(all_margins) / len(all_margins) if all_margins else Decimal("0")
    brand_summaries.insert(0, {
        "brand": "ALL",
        "deal_count": len(deals),
        "avg_margin": all_avg,
        "deals": deals[:DEALS_PAGE_SIZE],
        "deal_count_total": len(deals),
    })
    return brand_summaries, deals


def deals_swiper(request):
    from django.db.models import Avg, Count
    from market.models import DealSnapshot

    selected_currency = get_active_currency(request)

    if _clean_deals_available():
        brand_summaries, _all_clean_deals = _clean_brand_summaries()
    else:
        # Build brand summaries from cached legacy snapshots
        brand_stats = (
            DealSnapshot.objects
            .values("brand_name")
            .annotate(deal_count=Count("id"), avg_margin=Avg("margin_pct"))
            .order_by("-avg_margin")
        )

        brand_summaries = []
        for bs in brand_stats:
            deals = list(
                DealSnapshot.objects
                .select_related("listing__condition_audit")
                .filter(brand_name=bs["brand_name"])
                .order_by("-margin_pct")[:DEALS_PAGE_SIZE]
            )
            brand_summaries.append({
                "brand": bs["brand_name"],
                "deal_count": bs["deal_count"],
                "avg_margin": bs["avg_margin"] or 0,
                "deals": [_snapshot_to_dict(d) for d in deals],
                "deal_count_total": bs["deal_count"],
            })

        # ALL tab
        all_deals = list(
            DealSnapshot.objects
            .select_related("listing__condition_audit")
            .order_by("-margin_pct")[:DEALS_PAGE_SIZE]
        )
        all_margins = [d.margin_pct for d in all_deals if d.margin_pct is not None]
        all_avg = sum(all_margins) / len(all_margins) if all_margins else 0
        all_count = DealSnapshot.objects.count()
        brand_summaries.insert(0, {
            "brand": "ALL",
            "deal_count": all_count,
            "avg_margin": all_avg,
            "deals": [_snapshot_to_dict(d) for d in all_deals],
            "deal_count_total": all_count,
        })

    can_view_supplier = request.user.is_authenticated and request.user.is_staff

    def _deal_json_for_user(d):
        data = _deal_to_json(d)
        if not can_view_supplier:
            data.pop("supplier_usd", None)
        return data

    brand_data_list = [{
        "brand": bs["brand"],
        "deal_count": bs["deal_count"],
        "total_deals": bs["deal_count"],
        "avg_margin": float(bs["avg_margin"]),
        "loaded": min(DEALS_PAGE_SIZE, bs["deal_count"]),
        "deals": [_deal_json_for_user(d) for d in bs["deals"][:DEALS_PAGE_SIZE]],
    } for bs in brand_summaries]

    return render(
        request,
        "market/deals_swiper.html",
        base_context(request, "deals_swiper")
        | {
            "brand_summaries": brand_summaries,
            "brand_data_list": brand_data_list,
            "selected_currency": selected_currency,
            "can_view_supplier": can_view_supplier,
        },
    )


@require_http_methods(["GET"])
def deals_api(request):
    """Return more deals for a brand tab. ?brand=X&offset=N"""
    from market.models import DealSnapshot

    brand = request.GET.get("brand", "")
    offset = int(request.GET.get("offset", 0))
    limit = int(request.GET.get("limit", DEALS_PAGE_SIZE))

    if _clean_deals_available():
        deals_all = _clean_deal_dicts()
        if brand != "ALL":
            deals_all = [deal for deal in deals_all if deal["brand"] == brand]
        total = len(deals_all)
        deals = deals_all[offset:offset + limit]
        return JsonResponse({
            "ok": True,
            "brand": brand,
            "offset": offset,
            "total": total,
            "deals": [_deal_to_json(d) for d in deals],
        })

    if brand == "ALL":
        qs = DealSnapshot.objects.select_related("listing__condition_audit").all()
    else:
        qs = DealSnapshot.objects.select_related("listing__condition_audit").filter(brand_name=brand)

    total = qs.count()
    deals = list(qs.order_by("-margin_pct")[offset:offset + limit])
    return JsonResponse({
        "ok": True,
        "brand": brand,
        "offset": offset,
        "total": total,
        "deals": [_deal_to_json(d) for d in deals],
    })


DEALS_MORE_MAX_LIMIT = 30
logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def deals_more(request):
    """Return server-rendered HTML card fragments for lazy-loading.

    Query params:
        brand  – brand name or "ALL"
        offset – starting index (default 0)
        limit  – number of deals to return (default 10, max 30)
    """
    from django.template.loader import render_to_string
    from market.models import DealSnapshot

    brand = request.GET.get("brand", "ALL")[:120]

    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = min(DEALS_MORE_MAX_LIMIT, max(1, int(request.GET.get("limit", DEALS_PAGE_SIZE))))
    except (TypeError, ValueError):
        limit = DEALS_PAGE_SIZE

    logger.info("[deals_more] brand=%s offset=%s limit=%s", brand, offset, limit)

    if _clean_deals_available():
        deals_all = _clean_deal_dicts()
        if brand != "ALL":
            deals_all = [deal for deal in deals_all if deal["brand"] == brand]
        total = len(deals_all)
        deals = deals_all[offset:offset + limit]
    elif brand == "ALL":
        qs = DealSnapshot.objects.select_related("listing__condition_audit").all()
        total = qs.count()
        deals = list(qs.order_by("-margin_pct")[offset:offset + limit])
    else:
        qs = DealSnapshot.objects.select_related("listing__condition_audit").filter(brand_name=brand)
        total = qs.count()
        deals = list(qs.order_by("-margin_pct")[offset:offset + limit])

    logger.info("[deals_more] total=%s returned=%s", total, len(deals))

    can_view_supplier = request.user.is_authenticated and request.user.is_staff

    html = render_to_string(
        "market/partials/_deal_cards_fragment.html",
        {
            "deals": deals if _clean_deals_available() else [_snapshot_to_dict(d) for d in deals],
            "can_view_supplier": can_view_supplier,
        },
        request=request,
    )

    return JsonResponse({
        "ok": True,
        "brand": brand,
        "offset": offset,
        "total": total,
        "count": len(deals),
        "html": html,
    })


@staff_member_required
def instagram_ocr_ops(request):
    from market.clean_models import PhoneOpportunitySnapshot
    from market.management.commands.process_ocr_queue import process_instagram_post
    from market.parsers.ocr_backend import get_ocr_backend
    from market.models import ParsedListingCandidate, PhoneListing, RawListing

    def post_image_url(post):
        if not post:
            return ""
        path = post.thumbnail_local_path or post.media_local_path
        if not path:
            return ""
        media_root = Path(settings.MEDIA_ROOT).resolve()
        try:
            rel_path = Path(path).resolve().relative_to(media_root)
        except (OSError, ValueError):
            return path if str(path).startswith(("/media/", "http://", "https://")) else ""
        return f"{settings.MEDIA_URL.rstrip('/')}/{rel_path.as_posix()}"

    def raw_image_url(raw):
        if not raw:
            return ""
        image_url = raw.image_url or ""
        if image_url:
            if image_url.startswith(("http://", "https://", "/media/")):
                return image_url
            media_root = Path(settings.MEDIA_ROOT).resolve()
            try:
                rel_path = Path(image_url).resolve().relative_to(media_root)
                return f"{settings.MEDIA_URL.rstrip('/')}/{rel_path.as_posix()}"
            except (OSError, ValueError):
                pass
            return image_url
        post_id = (raw.raw_payload or {}).get("instagram_post_id")
        post = InstagramPost.objects.filter(pk=post_id).first() if post_id else None
        return post_image_url(post)

    def candidate_store_warranty(candidate):
        if not candidate:
            return ""
        specs = candidate.phone_specs_json or {}
        return specs.get("store_warranty") or ""

    def candidate_post_id(candidate):
        if not candidate or not candidate.raw_listing:
            return ""
        return (candidate.raw_listing.raw_payload or {}).get("instagram_post_id") or ""

    def candidate_deal_math(candidate):
        if not candidate or candidate.detected_category != ParsedListingCandidate.DetectedCategory.PHONE:
            return {}
        raw = candidate.raw_listing
        listing = getattr(raw, "phone_listing", None) if raw else None
        if not listing or not listing.phone_model_id or not listing.storage_gb or listing.price_eur is None:
            return {}
        snapshot = (
            PhoneOpportunitySnapshot.objects.filter(
                phone_model_id=listing.phone_model_id,
                storage_gb=listing.storage_gb,
            )
            .order_by("-generated_at", "-id")
            .first()
        )
        if not snapshot or snapshot.turkiye_avg_eur is None:
            return {
                "available": False,
                "algeria_price": money(listing.price_eur, "EUR"),
                "algeria_original": f"{listing.price_original} {listing.currency_original}".strip(),
                "note": "No Sahibinden match yet",
            }
        gross = Decimal(str(snapshot.turkiye_avg_eur)) - Decimal(str(listing.price_eur))
        gain = compute_gain_split(
            algeria_min_eur=listing.price_eur,
            turkiye_avg_eur=snapshot.turkiye_avg_eur,
            gross_margin_eur=gross,
        )
        return {
            "available": True,
            "algeria_price": money(listing.price_eur, "EUR"),
            "algeria_original": f"{listing.price_original} {listing.currency_original}".strip(),
            "sahibinden_avg": money(snapshot.turkiye_avg_eur, "EUR"),
            "sahibinden_count": snapshot.turkiye_count,
            "gross_margin": money(gross, "EUR"),
            "margin_percent": f"{snapshot.margin_percent}%" if snapshot.margin_percent is not None else "",
            "offer_price": gain.get("offer_price_to_buyer_eur") if gain else "",
            "buyer_gain": gain.get("buyer_gain_eur") if gain else "",
            "deal_quality": gain.get("deal_quality") if gain else "",
            "snapshot_id": snapshot.pk,
        }

    selected_source_id = request.POST.get("source_id") or request.GET.get("source_id") or ""
    mode = request.POST.get("mode") or request.GET.get("mode") or "pending"
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    try:
        limit = int(request.POST.get("limit") or request.GET.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 20))

    sources = list(
        Source.objects.filter(source_type=SourceType.INSTAGRAM)
        .annotate(
            total_posts=Count("instagrampost", distinct=True),
            pending_posts=Count(
                "instagrampost",
                filter=Q(instagrampost__needs_ocr=True, instagrampost__ocr_processed=False),
                distinct=True,
            ),
            processed_posts=Count(
                "instagrampost",
                filter=Q(instagrampost__ocr_processed=True),
                distinct=True,
            ),
        )
        .order_by("username", "name")
    )

    selected_source = None
    if selected_source_id:
        selected_source = Source.objects.filter(
            pk=selected_source_id,
            source_type=SourceType.INSTAGRAM,
        ).first()

    batch_results = []
    batch_summary = None
    if request.method == "POST":
        action = request.POST.get("action", "batch")
        if action == "fx_refresh":
            out = StringIO()
            try:
                call_command(
                    "fetch_exchange_rates",
                    dzd_per_eur_black=str(eur_rate_or_setting("DZD", "DZD_PER_EUR_BLACK")),
                    stdout=out,
                )
            except Exception as exc:
                if is_ajax:
                    return JsonResponse({"ok": False, "error": str(exc)}, status=500)
                messages.error(request, f"FX refresh failed: {exc}")
            else:
                payload = fx_converter_payload()
                payload["command_output"] = out.getvalue()
                if is_ajax:
                    return JsonResponse({"ok": True, "fx": payload})
                messages.success(request, "FX rates refreshed.")

        single_post_id = request.POST.get("post_id", "")
        qs = InstagramPost.objects.select_related("source").filter(source__source_type=SourceType.INSTAGRAM)
        if selected_source:
            qs = qs.filter(source=selected_source)

        if action == "preview":
            if mode == "pending":
                qs = qs.filter(needs_ocr=True, ocr_processed=False)
            elif mode == "reprocess":
                qs = qs.filter(ocr_processed=True)
            elif mode == "rebuild":
                qs = qs.filter(ocr_processed=True, ocrresult__isnull=False).distinct()
            else:
                qs = InstagramPost.objects.none()
            posts = list(qs.order_by("id")[:limit])
            return JsonResponse(
                {
                    "ok": True,
                    "rows": [
                        {
                            "post_id": post.pk,
                            "shortcode": post.shortcode,
                            "source": post.source.username if post.source else "",
                            "image_url": post_image_url(post),
                            "prompt": "",
                            "mode": mode,
                        }
                        for post in posts
                    ],
                }
            )
        if action == "single":
            qs = InstagramPost.objects.select_related("source").filter(
                pk=single_post_id,
                source__source_type=SourceType.INSTAGRAM,
            )
            rebuild_clean = False
            backend = get_ocr_backend(settings.OCR_BACKEND)
        elif mode == "pending":
            qs = qs.filter(needs_ocr=True, ocr_processed=False)
            rebuild_clean = False
            backend = get_ocr_backend(settings.OCR_BACKEND)
        elif mode == "reprocess":
            qs = qs.filter(ocr_processed=True)
            rebuild_clean = False
            backend = get_ocr_backend(settings.OCR_BACKEND)
        elif mode == "rebuild":
            qs = qs.filter(ocr_processed=True, ocrresult__isnull=False).distinct()
            rebuild_clean = True
            backend = None
        else:
            qs = InstagramPost.objects.none()
            rebuild_clean = False
            backend = None

        posts = list(qs.order_by("id")[: 1 if action == "single" else limit])
        processed = 0
        exported = 0
        errors = 0
        for post in posts:
            try:
                result = process_instagram_post(post, backend=backend, rebuild_clean=rebuild_clean)
                if not result.get("processed"):
                    errors += 1
                    batch_results.append({
                        "post": post,
                        "image_url": post_image_url(post),
                        "ok": False,
                        "error": result.get("error", "Skipped"),
                    })
                    continue
                processed += 1
                exported += 1 if result.get("exported") else 0
                candidate = result.get("candidate")
                raw = result.get("raw_listing")
                batch_results.append(
                    {
                        "post": post,
                        "image_url": post_image_url(post),
                        "ok": True,
                        "raw": raw,
                        "candidate": candidate,
                        "store_warranty": candidate_store_warranty(candidate),
                        "deal": candidate_deal_math(candidate),
                        "debug": result.get("debug") or {},
                        "post_id": post.pk,
                        "exported": result.get("exported"),
                        "category": result.get("structured_category") or (candidate.detected_category if candidate else ""),
                    }
                )
            except Exception as exc:
                errors += 1
                batch_results.append({
                    "post": post,
                    "image_url": post_image_url(post),
                    "ok": False,
                    "error": str(exc),
                    "debug": {"error": str(exc)},
                    "post_id": post.pk,
                })

        if not is_ajax:
            messages.success(
                request,
                f"Instagram OCR batch finished: processed {processed}, exported {exported}, errors {errors}.",
            )
        batch_summary = {"processed": processed, "exported": exported, "errors": errors}

    instagram_raw = RawListing.objects.filter(source_type=SourceType.INSTAGRAM)
    recent_candidates = list(
        ParsedListingCandidate.objects.select_related("raw_listing", "raw_listing__source")
        .filter(raw_listing__source_type=SourceType.INSTAGRAM)
        .order_by("-updated_at")[:25]
    )
    for candidate in recent_candidates:
        candidate.ops_image_url = raw_image_url(candidate.raw_listing)
        candidate.ops_store_warranty = candidate_store_warranty(candidate)
        candidate.ops_post_id = candidate_post_id(candidate)
        candidate.ops_deal = candidate_deal_math(candidate)

    stats = {
        "posts": InstagramPost.objects.filter(source__source_type=SourceType.INSTAGRAM).count(),
        "pending": InstagramPost.objects.filter(
            source__source_type=SourceType.INSTAGRAM,
            needs_ocr=True,
            ocr_processed=False,
        ).count(),
        "processed": InstagramPost.objects.filter(
            source__source_type=SourceType.INSTAGRAM,
            ocr_processed=True,
        ).count(),
        "raw": instagram_raw.count(),
        "raw_unknown": instagram_raw.filter(category_hint="unknown").count(),
        "candidates": ParsedListingCandidate.objects.filter(
            raw_listing__source_type=SourceType.INSTAGRAM
        ).count(),
        "phone_listings": PhoneListing.objects.filter(source_type=SourceType.INSTAGRAM).count(),
    }

    if request.method == "POST" and is_ajax:
        return JsonResponse(
            {
                "ok": True,
                "summary": batch_summary or {"processed": 0, "exported": 0, "errors": 0},
                "stats": stats,
                "rows": [
                    {
                        "post_id": row["post"].pk,
                        "shortcode": row["post"].shortcode,
                        "source": row["post"].source.username if row["post"].source else "",
                        "image_url": row.get("image_url", ""),
                        "ok": row.get("ok", False),
                        "raw_id": row.get("raw").pk if row.get("raw") else "",
                        "candidate_id": row.get("candidate").pk if row.get("candidate") else "",
                        "candidate_url": (
                            reverse("candidate_detail", args=[row["candidate"].pk])
                            if row.get("candidate")
                            else ""
                        ),
                        "brand": row.get("candidate").brand_text if row.get("candidate") else "",
                        "model": row.get("candidate").model_text if row.get("candidate") else "",
                        "price": row.get("candidate").price_original if row.get("candidate") else "",
                        "currency": row.get("candidate").currency_original if row.get("candidate") else "",
                        "confidence": row.get("candidate").confidence if row.get("candidate") else "",
                        "status": row.get("candidate").status if row.get("candidate") else "",
                        "category": row.get("category", ""),
                        "store_warranty": row.get("store_warranty", ""),
                        "deal": row.get("deal") or {},
                        "debug": row.get("debug") or {},
                        "post_id": row.get("post_id") or row["post"].pk,
                        "exported": bool(row.get("exported")),
                        "error": row.get("error", ""),
                    }
                    for row in batch_results
                ],
            }
        )

    return render(
        request,
        "dash/instagram_ocr_ops.html",
        base_context(request, "instagram_ocr_ops")
        | {
            "sources": sources,
            "selected_source_id": str(selected_source.pk) if selected_source else "",
            "mode": mode,
            "limit": limit,
            "stats": stats,
            "fx_converter": fx_converter_payload(),
            "batch_results": batch_results,
            "recent_candidates": recent_candidates,
        },
    )


@staff_member_required
def instagram_ocr_ops_v2(request):
    from django.template.response import TemplateResponse

    response = instagram_ocr_ops(request)
    if isinstance(response, TemplateResponse):
        response.template_name = "dash/instagram_ocr_ops.html"
        return response
    return response


@staff_member_required
def import_lab(request):
    from market.models import RawImportRun, RawListing, ParsedListingCandidate

    if request.method == "POST":
        return _import_lab_action(request)

    runs = RawImportRun.objects.order_by("-started_at")[:20]

    raw_status = request.GET.get("raw_status", "")
    raw_category = request.GET.get("raw_category", "")
    raw_source = request.GET.get("raw_source", "")

    raw_qs = RawListing.objects.select_related("import_run", "source").order_by("-observed_at")
    if raw_status:
        raw_qs = raw_qs.filter(parse_status=raw_status)
    if raw_category:
        raw_qs = raw_qs.filter(category_hint=raw_category)
    if raw_source:
        raw_qs = raw_qs.filter(source_type=raw_source)
    raw_listings = raw_qs[:100]

    candidate_status = request.GET.get("candidate_status", "")
    candidate_category = request.GET.get("candidate_category", "")

    candidate_qs = ParsedListingCandidate.objects.select_related(
        "raw_listing", "matched_brand",
    ).order_by("-created_at")
    if candidate_status:
        candidate_qs = candidate_qs.filter(status=candidate_status)
    if candidate_category:
        candidate_qs = candidate_qs.filter(detected_category=candidate_category)
    candidates = candidate_qs[:100]

    stats = {
        "total_raw": RawListing.objects.count(),
        "raw_by_status": dict(
            RawListing.objects.values_list("parse_status").annotate(c=Count("id")).values_list("parse_status", "c")
        ),
        "total_candidates": ParsedListingCandidate.objects.count(),
        "candidates_by_status": dict(
            ParsedListingCandidate.objects.values_list("status").annotate(c=Count("id")).values_list("status", "c")
        ),
        "total_runs": RawImportRun.objects.count(),
    }

    return render(
        request,
        "market/import_lab.html",
        base_context(request, "import_lab")
        | {
            "runs": runs,
            "raw_listings": raw_listings,
            "candidates": candidates,
            "stats": stats,
            "filters": {
                "raw_status": raw_status,
                "raw_category": raw_category,
                "raw_source": raw_source,
                "candidate_status": candidate_status,
                "candidate_category": candidate_category,
            },
            "raw_status_choices": RawListing.ParseStatus.choices,
            "category_choices": RawListing.CategoryHint.choices,
            "source_type_choices": SourceType.choices,
            "candidate_status_choices": ParsedListingCandidate.Status.choices,
            "candidate_category_choices": ParsedListingCandidate.DetectedCategory.choices,
        },
    )


def _import_lab_action(request):
    from market.models import ParsedListingCandidate, RawListing
    from market.services.parsing.candidate_builder import build_candidate

    action = request.POST.get("action", "")
    ids_raw = request.POST.get("ids", "")
    candidate_id = request.POST.get("candidate_id", "")

    if not ids_raw and not candidate_id:
        return JsonResponse({"ok": False, "error": "No items selected."}, status=400)

    if candidate_id:
        ids = [int(candidate_id)]
    else:
        try:
            ids = [int(x) for x in ids_raw.split(",") if x.strip()]
        except ValueError:
            return JsonResponse({"ok": False, "error": "Invalid IDs."}, status=400)

    if action == "approve":
        count = ParsedListingCandidate.objects.filter(id__in=ids).update(
            status=ParsedListingCandidate.Status.APPROVED
        )
        return JsonResponse({"ok": True, "action": "approved", "count": count})

    if action == "reject":
        count = ParsedListingCandidate.objects.filter(id__in=ids).update(
            status=ParsedListingCandidate.Status.REJECTED
        )
        return JsonResponse({"ok": True, "action": "rejected", "count": count})

    if action == "parse":
        parsed = 0
        errors = 0
        for raw_id in ids:
            try:
                raw = RawListing.objects.get(pk=raw_id)
                build_candidate(raw)
                parsed += 1
            except Exception:
                errors += 1
        return JsonResponse({"ok": True, "action": "parsed", "count": parsed, "errors": errors})

    if action == "export":
        from market.management.commands.export_candidates import Command as ExportCmd
        cmd = ExportCmd()
        cmd.stdout = sys.stdout
        exported = 0
        for cid in ids:
            try:
                candidate = ParsedListingCandidate.objects.get(pk=cid)
                if candidate.detected_category == ParsedListingCandidate.DetectedCategory.PHONE:
                    cmd._export_phone(candidate)
                elif candidate.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP:
                    cmd._export_laptop(candidate)
                else:
                    continue
                candidate.status = ParsedListingCandidate.Status.EXPORTED
                candidate.save(update_fields=["status"])
                if candidate.raw_listing:
                    candidate.raw_listing.parse_status = RawListing.ParseStatus.EXPORTED
                    candidate.raw_listing.save(update_fields=["parse_status"])
                exported += 1
            except Exception:
                pass
        return JsonResponse({"ok": True, "action": "exported", "count": exported})

    return JsonResponse({"ok": False, "error": f"Unknown action: {action}"}, status=400)


@staff_member_required
def candidate_detail(request, pk):
    from market.models import ParsedListingCandidate
    from market.services.parsing.segments import SEGMENT_COLORS

    candidate = get_object_or_404(
        ParsedListingCandidate.objects.select_related(
            "raw_listing", "matched_brand", "matched_phone_model",
            "matched_phone_variant", "matched_laptop_model", "matched_laptop_variant",
        ),
        pk=pk,
    )

    raw = candidate.raw_listing
    segments = candidate.detected_segments_json or []
    highlighted_text = ""
    if raw:
        text = raw.raw_text or raw.title_raw or ""
        if segments:
            parts = []
            pos = 0
            for seg in sorted(segments, key=lambda s: s.get("start", 0)):
                start = max(seg.get("start", 0), pos)
                if start > pos:
                    from django.utils.html import escape
                    parts.append(f'<span>{escape(text[pos:start])}</span>')
                color = SEGMENT_COLORS.get(seg.get("label", ""), "#9ca3af")
                from django.utils.html import escape
                parts.append(
                    f'<span style="background-color:{color}33;border-bottom:2px solid {color};'
                    f'padding:1px 2px;border-radius:2px" title="{seg.get("label", "")} '
                    f'({seg.get("confidence", 0):.0%})">{escape(text[start:seg.get("end", start)])}</span>'
                )
                pos = seg.get("end", start)
            if pos < len(text):
                from django.utils.html import escape
                parts.append(f'<span>{escape(text[pos:])}</span>')
            highlighted_text = "\n".join(parts)
        else:
            from django.utils.html import escape
            highlighted_text = f"<pre>{escape(raw.raw_text or '')}</pre>"

    enriched_segments = []
    for seg in segments:
        enriched_segments.append({
            **seg,
            "color": SEGMENT_COLORS.get(seg.get("label", ""), "#9ca3af"),
        })

    return render(
        request,
        "market/candidate_detail.html",
        base_context(request, "import_lab")
        | {
            "candidate": candidate,
            "raw": raw,
            "segments": enriched_segments,
            "highlighted_text": highlighted_text,
        },
    )
