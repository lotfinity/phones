from django import template

from market.services.brand_logos import brand_initial as _brand_initial
from market.services.brand_logos import brand_logo_url as _brand_logo_url
from market.services.brand_logos import simple_icon_slug as _simple_icon_slug

register = template.Library()


@register.filter(name="brand_logo_url")
def brand_logo_url(value):
    return _brand_logo_url(value)


@register.filter(name="brand_initial")
def brand_initial(value):
    return _brand_initial(value)


@register.filter(name="simple_icon_slug")
def simple_icon_slug(value):
    return _simple_icon_slug(value)
