#!/usr/bin/env python3
"""Build an OpenAPI 3.0.3 document (and a Markdown endpoint catalogue) from a compact endpoint table.

Usage:
  python3 -I gen_openapi.py ENDPOINTS.json --out openapi.json [--md-catalogue catalogue.md] [--routes conf/prod.routes]

ENDPOINTS.json format (only "info" and "endpoints" are required):
{
  "info": {"title": "...", "description": "...", "version": "1.0.0"},
  "servers": [{"url": "http://localhost:9000"}],
  "tags": [{"name": "Customers", "description": "..."}],          # optional; order defaults to first use
  "components": {"schemas": {...}, "responses": {...}, "securitySchemes": {...}},
  "security": [...],                                              # optional global security
  "headerDescriptions": {"userinfo": "Caller identity"},          # used for headers given by name only
  "headersLabel": "Request headers used",                         # prefix of the header list in descriptions
  "defaultResponses": {                                           # merged under each endpoint's own responses
    "all":      {"default": "Upstream", "500": "Unreachable"},   # string = #/components/responses/<name>
    "withBody": {"400": "BadRequest"}                             # added when the endpoint has a request body
  },
  "endpoints": [
    {
      "method": "GET", "path": "/customer/{srn}", "operationId": "getCustomer",
      "tag": "Customers", "summary": "Fetch a customer",
      "notes": "Free text added to the description.",
      "params": ["p:srn", "q?:page:int", "q:itemsPerPage:int=20|Page size", "q*:status", "h:X-Client-ID", "q~"],
      "headers": ["userinfo", {"name": "X-Client-ID", "required": true, "description": "..."}],
      "body": "json" | "none" | "text" | "binary" | {"contentType": "...", "schema": {...}, "description": "..."},
      "responses": {"200": {"description": "OK"}, "404": "NotFound", "500": null},   # null removes a default
      "auth": "Stride role X",                                     # free text, shown in the catalogue
      "security": [...],                                           # raw OpenAPI security for this operation
      "downstream": {"service": "customer", "method": "GET", "path": "/customer/{srn}"},  # becomes x-downstream
      "noDefaults": false                                          # true = skip defaultResponses
    }
  ]
}

Parameter DSL: KIND:name[:type][=default][|description]
  p   path (required)          types: string (default), int, long, number, boolean, multi (path spanning segments)
  q   required query           q?  optional query           q*  repeatable query (array, form/explode)
  h   required header          h?  optional header          q~  "any query parameters" (free-form object)
A parameter may also be a raw OpenAPI parameter object.

Checks (exit 1 on failure): unique operationIds, path template params == declared path params, every $ref resolves,
and with --routes the (method, path) set equals the Play routes (following `->` includes found next to the file).
"""
import argparse
import json
import os
import re
import sys

TYPES = {
    "string": {"type": "string"},
    "int": {"type": "integer", "format": "int32"},
    "long": {"type": "integer", "format": "int64"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
}
RESERVED_HEADERS = {"accept", "content-type", "content-length", "authorization"}  # OpenAPI ignores these as header parameters
BODY_KINDS = {
    "json": ("application/json", {"description": "Free-form JSON."}, "JSON document."),
    "text": ("*/*", {"type": "string"}, "Raw body, read as text."),
    "binary": ("application/octet-stream", {"type": "string", "format": "binary"}, "Raw bytes."),
}


def cast(typ, value):
    if typ in ("int", "long"):
        return int(value)
    if typ == "number":
        return float(value)
    if typ == "boolean":
        return value == "true"
    return value


def parse_param(spec, header_desc):
    if isinstance(spec, dict):
        return spec
    if spec == "q~":
        return {"name": "params", "in": "query", "required": False, "style": "form", "explode": True,
                "description": "Any query parameters; forwarded unchanged.",
                "schema": {"type": "object", "additionalProperties": {"type": "string"}}}
    desc = None
    if "|" in spec:
        spec, desc = spec.split("|", 1)
    kind, rest = spec.split(":", 1)
    default = None
    if "=" in rest:
        rest, default = rest.split("=", 1)
    parts = rest.split(":")
    name, typ = parts[0], (parts[1] if len(parts) > 1 else "string")
    p = {"name": name}
    if kind == "p":
        p.update({"in": "path", "required": True})
        if typ == "multi":
            p["schema"] = {"type": "string"}
            p["allowReserved"] = True
            desc = desc or "One or more path segments separated by `/`."
        else:
            p["schema"] = dict(TYPES[typ])
    elif kind in ("q", "q?"):
        s = dict(TYPES[typ])
        if default is not None:
            s["default"] = cast(typ, default)
        p.update({"in": "query", "required": kind == "q" and default is None, "schema": s})
    elif kind == "q*":
        p.update({"in": "query", "required": False, "style": "form", "explode": True,
                  "schema": {"type": "array", "items": dict(TYPES[typ])}})
        desc = desc or "Repeatable."
    elif kind in ("h", "h?"):
        p.update({"in": "header", "required": kind == "h", "schema": {"type": "string"}})
        desc = desc or header_desc.get(name)
    else:
        raise ValueError(f"unknown parameter kind in {spec!r}")
    if desc:
        p["description"] = desc
    return p


def resolve_response(value):
    return {"$ref": f"#/components/responses/{value}"} if isinstance(value, str) else value


def build_operation(e, cfg):
    header_desc = cfg.get("headerDescriptions", {})
    op = {"tags": [e["tag"]], "summary": e["summary"], "operationId": e["operationId"]}

    params = [parse_param(s, header_desc) for s in e.get("params", [])]
    header_names = []
    for h in e.get("headers", []):
        h = {"name": h} if isinstance(h, str) else h
        header_names.append(h["name"])
        if h["name"].lower() in RESERVED_HEADERS or any(p["in"] == "header" and p["name"].lower() == h["name"].lower() for p in params):
            continue
        params.append({"name": h["name"], "in": "header", "required": h.get("required", False),
                       "description": h.get("description", header_desc.get(h["name"], "")), "schema": {"type": "string"}})
    if params:
        op["parameters"] = params

    desc = []
    ds = e.get("downstream")
    if ds:
        desc.append(f"Proxied to **{ds['service']}** as `{ds['method']} {ds['path']}`.")
        op["x-downstream"] = ds
    if e.get("auth"):
        desc.append(f"Auth: {e['auth']}.")
    if e.get("notes"):
        desc.append(e["notes"])
    if header_names:
        desc.append(cfg.get("headersLabel", "Request headers used") + ": " + ", ".join(f"`{h}`" for h in header_names) + ".")
    if desc:
        op["description"] = "\n\n".join(desc)

    body = e.get("body", "none")
    if body != "none":
        if isinstance(body, str):
            ctype, schema, bdesc = BODY_KINDS[body]
            body = {"contentType": ctype, "schema": schema, "description": cfg.get("bodyDescriptions", {}).get(e["body"], bdesc)}
        op["requestBody"] = {"required": body.get("required", True),
                             "description": body.get("description", ""),
                             "content": {body.get("contentType", "application/json"): {"schema": body.get("schema", {})}}}

    responses = {}
    if not e.get("noDefaults"):
        defaults = cfg.get("defaultResponses", {})
        responses.update(defaults.get("all", {}))
        if body != "none":
            responses.update(defaults.get("withBody", {}))
    responses.update(e.get("responses", {}))
    responses = {k: resolve_response(v) for k, v in responses.items() if v is not None}
    if not responses:
        responses = {"default": {"description": "Response."}}
    op["responses"] = dict(sorted(responses.items(), key=lambda kv: (kv[0] == "default", kv[0])))
    if "security" in e:
        op["security"] = e["security"]
    return op


def play_routes(path, prefix=""):
    """Yield (METHOD, /path) from a Play routes file, following `->` includes that exist next to it."""
    base = os.path.dirname(path)
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "->":
            sub = os.path.join(base, parts[2][: -len(".Routes")].lower() + ".routes") if parts[2].endswith(".Routes") else None
            if sub and os.path.exists(sub):
                yield from play_routes(sub, (prefix + "/" + parts[1].strip("/")).rstrip("/"))
            else:
                print(f"note: include {parts[2]} not found locally (library router?), skipped", file=sys.stderr)
            continue
        method, route = parts[0], parts[1]
        route = re.sub(r"\$(\w+)<[^>]+>", r"{\1}", route)
        route = re.sub(r"[:*](\w+)", r"{\1}", route)
        yield method, (prefix + route) or "/"


def check(spec, endpoints, routes_file):
    errors = []
    ids = [e["operationId"] for e in endpoints]
    errors += [f"duplicate operationId {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for p, ops in spec["paths"].items():
        for m, o in ops.items():
            declared = [x["name"] for x in o.get("parameters", []) if x.get("in") == "path"]
            if sorted(declared) != sorted(re.findall(r"{(\w+)}", p)):
                errors.append(f"{m.upper()} {p}: path params {declared} do not match template")
    text = json.dumps(spec)
    for kind, name in set(re.findall(r'"#/components/(\w+)/([^"]+)"', text)):
        if name not in spec.get("components", {}).get(kind, {}):
            errors.append(f"unresolved $ref #/components/{kind}/{name}")
    if routes_file:
        routes = set(play_routes(routes_file))
        documented = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
        errors += [f"route not documented: {m} {p}" for m, p in sorted(routes - documented)]
        extra = sorted(documented - routes)
        if extra:
            print("note: documented but not in routes (library/platform routes?): " +
                  ", ".join(f"{m} {p}" for m, p in extra), file=sys.stderr)
    return errors


def catalogue(endpoints, tags):
    show_ds = any(e.get("downstream") for e in endpoints)
    show_auth = any(e.get("auth") for e in endpoints)
    head = ["Method", "Path", "Purpose"] + (["Auth"] if show_auth else []) + (["Back end"] if show_ds else [])
    out = []
    for tag in tags:
        rows = [e for e in endpoints if e["tag"] == tag]
        out += [f"\n### {tag}\n", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for e in rows:
            cells = [e["method"], f"`{e['path']}`", e["summary"]]
            if show_auth:
                cells.append(e.get("auth", "—"))
            if show_ds:
                ds = e.get("downstream")
                if ds:
                    names = " or ".join(f"`{s.strip()}`" for s in ds["service"].split("|"))
                    same = ds["method"] == e["method"] and ds["path"] == e["path"]
                    cells.append(names + ("" if same else f" → `{ds['method']} {ds['path']}`"))
                else:
                    cells.append("— (served locally)")
            out.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("endpoints")
    ap.add_argument("--out", required=True)
    ap.add_argument("--md-catalogue")
    ap.add_argument("--routes")
    a = ap.parse_args()

    cfg = json.load(open(a.endpoints))
    endpoints = cfg["endpoints"]
    tags = [t["name"] for t in cfg.get("tags", [])]
    for e in endpoints:
        if e["tag"] not in tags:
            tags.append(e["tag"])

    paths = {}
    for e in endpoints:
        method = e["method"].lower()
        if method in paths.get(e["path"], {}):
            sys.exit(f"duplicate operation {e['method']} {e['path']}")
        paths.setdefault(e["path"], {})[method] = build_operation(e, cfg)

    spec = {"openapi": "3.0.3", "info": cfg["info"]}
    if cfg.get("servers"):
        spec["servers"] = cfg["servers"]
    if cfg.get("security"):
        spec["security"] = cfg["security"]
    tag_desc = {t["name"]: t for t in cfg.get("tags", [])}
    spec["tags"] = [tag_desc.get(t, {"name": t}) for t in tags]
    spec["paths"] = paths
    if cfg.get("components"):
        spec["components"] = cfg["components"]

    errors = check(spec, endpoints, a.routes)
    if errors:
        print("\n".join("error: " + x for x in errors), file=sys.stderr)
        sys.exit(1)

    with open(a.out, "w") as f:
        json.dump(spec, f, indent=2)
        f.write("\n")
    if a.md_catalogue:
        with open(a.md_catalogue, "w") as f:
            f.write(catalogue(endpoints, tags))
    print(f"{len(endpoints)} operations, {len(paths)} paths -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
