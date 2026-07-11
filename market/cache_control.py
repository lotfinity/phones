from functools import wraps

from django.utils.cache import patch_cache_control, patch_vary_headers


def private_no_store(view_func):
    """Prevent shared caches from reusing user-specific HTML responses."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        patch_cache_control(
            response,
            private=True,
            no_cache=True,
            no_store=True,
            must_revalidate=True,
            max_age=0,
        )
        patch_vary_headers(response, ("Cookie",))
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        response["CDN-Cache-Control"] = "no-store"
        response["Cloudflare-CDN-Cache-Control"] = "no-store"
        response["Surrogate-Control"] = "no-store"

        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_superuser:
            viewer = "superuser"
        elif user and user.is_authenticated and user.is_staff:
            viewer = "staff"
        elif user and user.is_authenticated:
            viewer = "authenticated"
        else:
            viewer = "public"
        response["X-PriceBridge-Viewer"] = viewer
        return response

    return wrapped
