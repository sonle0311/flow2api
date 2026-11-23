"""Read-only integration contracts derived from the running route/model registries."""

from copy import deepcopy
import re

from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Mount

from .integration_docs import ENDPOINT_NOTES
from .model_resolver import (
    IMAGE_BASE_MODELS,
    MODEL_SUPPORTED_ASPECTS,
    MODEL_SUPPORTED_SIZES,
    get_base_model_aliases,
    get_model_parameter_contracts,
)
from ..services.generation_handler import MODEL_CONFIG


def _dependency_names(dependant):
    names = set()
    for dependency in getattr(dependant, "dependencies", ()):
        names.add(getattr(dependency.call, "__name__", ""))
        names.update(_dependency_names(dependency))
    return names


def _authentication(route):
    if route.path in {"/browser-desktop/", "/api/browser-desktop/ws"}:
        return "admin_session"
    if route.path in {"/api/plugin/update-token", "/api/plugin/check-tokens"}:
        return "plugin_connection_token"
    if isinstance(route, APIWebSocketRoute):
        return "api_key"
    names = _dependency_names(getattr(route, "dependant", None))
    if "verify_admin_token" in names or route.path in {"/manage", "/test"}:
        return "admin_session"
    if names.intersection({"verify_api_key_flexible", "verify_api_key_header"}):
        return "api_key"
    return "public"


def build_integration_reference(app):
    """Return schemas, static examples and model capabilities, never account/config secrets."""
    specification = app.openapi()
    endpoints = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue
        if isinstance(route, APIWebSocketRoute):
            methods = ["WEBSOCKET"]
        elif isinstance(route, Mount):
            methods = ["MOUNT"]
        else:
            methods = sorted(getattr(route, "methods", ()) or ())
        for method in methods:
            operation = specification.get("paths", {}).get(path, {}).get(method.lower(), {})
            endpoints.append({
                "method": method,
                "path": path,
                "auth": _authentication(route),
                "summary": operation.get("summary") or getattr(route, "name", path),
                "description": operation.get("description", ""),
                "parameters": deepcopy(operation.get("parameters", [])),
                "request_body": deepcopy(operation.get("requestBody")),
                "responses": deepcopy(operation.get("responses", {})),
                "notes": deepcopy(ENDPOINT_NOTES.get(f"{method} {path}", {})),
            })

    models = []
    for model_id, config in sorted(MODEL_CONFIG.items()):
        duration = re.search(r"(?:_|-)(\d+)s(?:_|-|$)", model_id)
        upsample = config.get("upsample")
        if isinstance(upsample, dict):
            upsample = upsample.get("resolution")
        models.append({
            "id": model_id,
            "listed": bool(config.get("listed", True)),
            "display_name": config.get("display_name", ""),
            "type": config["type"],
            "video_type": config.get("video_type"),
            "aspect_ratio": config.get("aspect_ratio"),
            "supports_images": config.get("supports_images", config["type"] == "image"),
            "min_images": config.get("min_images", 0),
            # R2V/Omni allow a zero-reference request through local validation;
            # the configured minimum is still relevant to upstream capability.
            "locally_validated_min_images": config.get("min_images", 0) if config.get("video_type") == "i2v" else 0,
            "max_images": config.get("max_images"),
            "duration_seconds": config.get("reference_duration") or (int(duration[1]) if duration else None),
            "upsample": upsample,
        })

    aliases = []
    for alias, description in sorted(get_base_model_aliases().items()):
        image_base = IMAGE_BASE_MODELS.get(alias)
        aliases.append({
            "id": alias,
            "type": "image" if image_base else "video",
            "description": description,
            "aspects": list(MODEL_SUPPORTED_ASPECTS.get(image_base, ["landscape", "portrait"])),
            "image_sizes": list(MODEL_SUPPORTED_SIZES.get(image_base, [])),
        })

    return {
        "version": 1,
        "endpoints": sorted(endpoints, key=lambda endpoint: (endpoint["path"], endpoint["method"])),
        "models": models,
        "aliases": aliases,
        "model_parameters": get_model_parameter_contracts(MODEL_CONFIG),
        "schemas": deepcopy(specification.get("components", {}).get("schemas", {})),
    }


_LOCAL_BROWSER_CAPTCHA_METHODS = {"personal", "browser", "managed"}


def _limit(value):
    """Normalize a configured limit: positive int, or None for unlimited/off."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def build_capacity(settings, tokens):
    """Throughput limits a client should respect, from the running configuration.

    Only numbers and the captcha method name are returned: no account
    identities, credentials, URLs or API keys.
    """
    method = str(settings.captcha_method or "")
    captcha_slots = None
    if method == "personal":
        captcha_slots = min(50, settings.browser_count * settings.personal_max_resident_tabs)
    elif method == "browser":
        captcha_slots = settings.browser_count

    def per_kind(kind):
        enabled = [t for t in tokens if t.is_active and getattr(t, f"{kind}_enabled", True)]
        limits = [_limit(getattr(t, f"{kind}_concurrency", -1)) for t in enabled]
        accounts_limit = None if not enabled or None in limits else sum(limits)
        launch_limit = _limit(getattr(settings, f"flow_{kind}_launch_soft_limit"))
        bounds = [b for b in (captcha_slots, launch_limit, accounts_limit) if b is not None]
        return {
            "active_accounts": len(enabled),
            "per_account_concurrency": sorted({-1 if v is None else v for v in limits}),
            "accounts_total_concurrency": accounts_limit,
            "launch_soft_limit": launch_limit,
            "launch_stagger_ms": max(0, int(getattr(settings, f"flow_{kind}_launch_stagger_ms") or 0)),
            "queue_wait_timeout_seconds": int(getattr(settings, f"flow_{kind}_slot_wait_timeout")),
            # 0 means no account can currently serve this kind of request.
            "recommended_max_parallel_requests": 0 if not enabled else (min(bounds) if bounds else None),
        }

    return {
        "captcha_method": method,
        "captcha_third_party": method not in _LOCAL_BROWSER_CAPTCHA_METHODS and method != "remote_browser",
        "captcha_parallel_slots": captcha_slots,
        "image": per_kind("image"),
        "video": per_kind("video"),
    }
