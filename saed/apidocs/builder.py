"""
OpenAPI 3.1 document generator for the SAED API.

The spec is *derived from the live URLconf* so it cannot silently drift:

* paths / methods  -> ``saed.urls`` (every route is included; a test enforces it)
* access rules     -> each view's ``permission_classes`` (``HasRole.roles``)
* request fields   -> ``request.data.get("x")`` usages in the view source
* query parameters -> ``request.query_params.get("x")`` usages in the view source
* human text       -> ``curated.py`` (summaries, descriptions, schemas)
"""
import inspect
import re
from functools import lru_cache

from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny

from . import curated

API_PREFIX = "/api"
HIDDEN_PATHS = {"_sys/ops/"}          # operational bootstrap route: intentionally undocumented
METHODS = ("get", "post", "put", "patch", "delete")
_CONV = {"int": ("integer", None), "str": ("string", None), "uuid": ("string", "uuid"), "slug": ("string", None)}

_DATA_RE = re.compile(r"""(?:request\.data|data|payload|body)\s*(?:\.get\(|\[)\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_QUERY_RE = re.compile(r"""query_params\s*\.get\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_FILE_RE = re.compile(r"""request\.FILES(?:\.get\(|\[)\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_INT_HINT = re.compile(r"(?:^|_)(?:id|ids|page|pageSize|page_size|limit|offset|order|position|index)$|Id$|Ids$", re.I)
_NUM_HINT = re.compile(r"amount|price|fee|rate|percent|duration|score", re.I)
_BOOL_HINT = re.compile(r"^(?:is|has|enable|enabled|published|restricted|premium|paid|isPublished|isPremium)|Enabled$", re.I)


def _humanise(name):
    name = re.sub(r"View$", "", name)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).strip()


def _guess(name):
    if _BOOL_HINT.search(name):
        return {"type": "boolean"}
    if _NUM_HINT.search(name):
        return {"type": "number"}
    if _INT_HINT.search(name):
        return {"type": ["integer", "string"]}
    return {"type": "string"}


def _walk(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


def _path_params(route):
    params = []
    for conv, name in re.findall(r"<(?:(\w+):)?(\w+)>", route):
        typ, fmt = _CONV.get(conv or "str", ("string", None))
        schema = {"type": typ}
        if fmt:
            schema["format"] = fmt
        params.append({"name": name, "in": "path", "required": True, "schema": schema,
                       "description": curated.PATH_PARAMS.get(name, "")})
    return params


def _roles_of(cls):
    perms = getattr(cls, "permission_classes", None)
    if perms is None:
        return "authenticated", ()
    if not perms:
        return "public", ()
    out = set()
    for p in perms:
        if p is AllowAny:
            return "public", ()
        roles = getattr(p, "roles", None)
        if roles:
            out.update(roles)
        elif p.__name__ == "_AdminReadDunisWrite":
            return "split", ("saed_admin", "dunis_admin")
    return ("roles", tuple(sorted(out))) if out else ("authenticated", ())


def _source(cls, method):
    try:
        return inspect.getsource(getattr(cls, method))
    except (OSError, TypeError):
        return ""


def _fields(src, regex):
    seen = []
    for m in regex.findall(src):
        if m not in seen:
            seen.append(m)
    return seen


def _operation(route, method, view, cls):
    key = f"{method.upper()} /{route}"
    cur = curated.OPERATIONS.get(key, {})
    kind, roles = _roles_of(cls) if cls else ("public", ())
    if kind == "split":
        roles_txt = "Read: `saed_admin`, `dunis_admin`. Write: `dunis_admin` only."
    elif kind == "roles":
        roles_txt = "Roles: " + ", ".join(f"`{r}`" for r in roles) + "."
    elif kind == "public":
        roles_txt = "Public (no authentication)."
    else:
        roles_txt = "Any authenticated user."

    doc = inspect.getdoc(getattr(cls, method, None)) if cls else inspect.getdoc(view)
    doc = doc or ""
    summary = cur.get("summary") or (doc.splitlines()[0] if doc else f"{_humanise(cls.__name__ if cls else view.__name__)} ({method.upper()})")
    desc = cur.get("description") or "\n".join(doc.splitlines()[1:]).strip()
    description = (desc + "\n\n" if desc else "") + f"**Access.** {roles_txt}"

    tag = curated.tag_for(route)
    op = {
        "operationId": curated.operation_id(method, route),
        "tags": [tag], "summary": summary, "description": description,
        "x-roles": list(roles) if roles else ([] if kind in ("public", "authenticated") else []),
        "parameters": _path_params(route),
    }
    if kind == "public":
        op["security"] = []
    else:
        op["security"] = [{"sessionAuth": []}]

    src = _source(cls, method) if cls else ""
    for q in cur.get("query", None) or _fields(src, _QUERY_RE):
        spec = q if isinstance(q, dict) else {"name": q}
        name = spec["name"]
        op["parameters"].append({"name": name, "in": "query", "required": False,
                                 "schema": spec.get("schema", {"type": "string"}),
                                 "description": spec.get("description", curated.QUERY_PARAMS.get(name, ""))})

    if method in ("post", "put", "patch"):
        files = _fields(src, _FILE_RE)
        body = cur.get("body")
        if body is None:
            names = _fields(src, _DATA_RE)
            if names or files:
                body = {"type": "object", "properties": {n: {**_guess(n), "description": curated.FIELDS.get(n, "")} for n in names}}
        if body is not None or files:
            content = {}
            if body is not None:
                content["application/json"] = {"schema": body}
            if files:
                props = {n: {"type": "string", "format": "binary"} for n in files}
                props.update({k: v for k, v in (body or {}).get("properties", {}).items()})
                content["multipart/form-data"] = {"schema": {"type": "object", "properties": props}}
            op["requestBody"] = {"required": bool(cur.get("body_required", True)), "content": content}

    responses = {"200": cur.get("response", {"description": "Success.",
                 "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}})}
    if method == "post" and cur.get("created"):
        responses = {"201": responses["200"]}
    if method in ("post", "put", "patch") or "query" in op and op["parameters"]:
        responses["400"] = {"$ref": "#/components/responses/BadRequest"}
    if kind != "public":
        responses["401"] = {"$ref": "#/components/responses/Unauthorized"}
        if kind in ("roles", "split") or method != "get":
            responses["403"] = {"$ref": "#/components/responses/Forbidden"}
    if any(p["in"] == "path" for p in op["parameters"]):
        responses["404"] = {"$ref": "#/components/responses/NotFound"}
    if cls is not None and getattr(cls, "throttle_scope", None):
        responses["429"] = {"$ref": "#/components/responses/TooManyRequests"}
    for code, ref in cur.get("extra_responses", {}).items():
        responses[str(code)] = ref
    op["responses"] = dict(sorted(responses.items()))
    if method in ("post", "put", "patch", "delete") and kind != "public":
        op["x-csrf"] = "Requires the `X-CSRFToken` header (see `GET /csrf/`)."
    return op


@lru_cache(maxsize=1)
def build_spec():
    paths = {}
    for route, pat in _walk(get_resolver().url_patterns):
        if not route.startswith("api/"):
            continue
        route = route[len("api/"):]
        if route in HIDDEN_PATHS:
            continue
        cb = pat.callback
        cls = getattr(cb, "view_class", None) or getattr(cb, "cls", None)
        oas_path = "/" + re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", route)
        item = paths.setdefault(oas_path, {})
        if cls is None:  # function view
            allowed = getattr(cb, "view_is_async", None)  # noqa: F841
            methods = curated.FUNCTION_VIEW_METHODS.get(route, ("get",))
            for m in methods:
                item[m] = _operation(route, m, cb, None)
            continue
        for m in METHODS:
            if hasattr(cls, m):
                item[m] = _operation(route, m, cb, cls)

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SAED Learning Platform API",
            "version": curated.API_VERSION,
            "summary": "REST API for the SAED In-Camp / Post-Camp learning platform.",
            "description": curated.DESCRIPTION,
            "license": {"name": "Proprietary"},
        },
        "servers": [{"url": API_PREFIX, "description": "This server"}],
        "tags": [{"name": n, "description": d} for n, d in curated.TAGS],
        "paths": dict(sorted(paths.items())),
        "components": {
            "securitySchemes": {
                "sessionAuth": {"type": "apiKey", "in": "cookie", "name": settings.SESSION_COOKIE_NAME,
                                "description": "Django session cookie set by `POST /auth/login/`. "
                                               "Unsafe methods must also send `X-CSRFToken` (from `GET /csrf/`)."}},
            "schemas": curated.SCHEMAS,
            "responses": curated.RESPONSES,
        },
    }
