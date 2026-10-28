---
name: service-docs
description: Analyze a backend service's codebase and write documents at the repo root (skipping any that already exist) - service.md (a generic, business-level summary of what the service does), dependencies.md (every external dependency, how it is accessed, and what it is used for) validation.md (how data is validated at each boundary and what happens on failure), identifiers.md (every business identifier, its source, usage and validation rules) and openapi.json + openapi.md (OpenAPI 3 spec of the exposed HTTP endpoints, generated with a bundled script, plus a Markdown summary). Use when the user asks to analyze, summarize or document what a service does, its external dependencies/integrations, its data validation patterns, its business identifiers, or its HTTP endpoints / OpenAPI spec.
---

# Service documentation: `service.md` + `dependencies.md` + `validation.md` + `identifiers.md` + `openapi.json`/`openapi.md`

Produce these documents at the repository root. If the user asks for only some of them, write only those.

**Skip documents that already exist.** Before investigating, check the repository root for each target file (`service.md`, `dependencies.md`, `validation.md`, `identifiers.md`, `openapi.json`, `openapi.md`). `openapi.json` and `openapi.md` are a pair: skip the pair only when both exist, and if just one exists, write only the missing one. Leave any that already exist untouched: don't regenerate, overwrite or edit them. Only investigate what the remaining documents need. You may read the existing files as context. When you finish, list which files you skipped because they were already present. If every target file already exists, write nothing and tell the user so. Only regenerate or update an existing file if the user explicitly asks for that file to be refreshed.

## Step 1 – Investigate (read before writing)

Gather facts from the code, not just the README. Typical sources, in this order:

1. **README / docs folder**: the stated purpose, the frontend it pairs with, ports, run profiles.
2. **Inbound API surface**: route files (e.g. `conf/*.routes` in Play, controllers in Spring or Express, OpenAPI specs). Group the endpoints by capability. For the OpenAPI step, record for every endpoint: its parameters with their types, and which are required or have defaults; its body parser or reader; the headers it reads or forwards; its auth guard; the statuses it can return; and, for proxies, the upstream service, method and path.
3. **Controllers and services**: the real business rules (validation, eligibility checks, matching logic, side effects such as emails or audit events).
4. **Outbound integrations**: connectors and clients (`app/connectors`, `*Client*`, `*Connector*`). For each one, note the base URL source, paths, HTTP methods, headers, authentication scheme, correlation IDs, payload validation, and error and status mapping.
5. **Configuration**: `application.conf`, `application.yml`, `.env`. Look for service base URLs, path templates, credentials and tokens (refer to them by key name only, never values), TTLs, encryption flags, and feature flags.
6. **Persistence**: repositories, collections and tables, keys, indexes, TTL and expiry rules, and encryption at rest.
7. **Auth**: the action builders, filters or middleware that check identity, roles or enrolments, and any service-to-service auth.
8. **Cross-cutting concerns**: auditing and telemetry, feature toggles (what each toggle switches between), and callbacks/webhooks *into* the service.
9. **Build dependencies** (`build.sbt`, `project/AppDependencies.scala`, `pom.xml`, `package.json`): the libraries that back the integrations.
10. **Validation** (feeds `validation.md`): look at every boundary in turn.
    - Route/path binders: `PathBindable`, regexes, typed params.
    - Header and query presence checks.
    - Request-body readers, deserialisers or schemas (Play JSON `Reads`, Jackson, Bean Validation `@Valid`, zod or joi). Note which fields are required and which are optional, and look for format constraints (`pattern`, `minLength`, `verifying`, `filter`, regex). Their **absence** is a finding too.
    - Normalisation and derivation done inside the readers (ID clean-up, enum mapping, defaulting, silently dropping incomplete items).
    - External validation services (e.g. bank or address checks), and whether they fail open or closed.
    - Outbound payload checks (JSON Schema files: which ones are actually loaded, and are they checked before sending or only after an upstream rejection?).
    - Parsing of upstream responses.
    - Callback/webhook bodies and ids.
    - Size limits.

    For each failure path, trace the HTTP status the caller actually gets. Check in particular whether exceptions thrown **synchronously**, outside the `Future`/promise that the error handler guards, turn into 500s instead of 400s. Grep for `withName`, `.as[`, `.get`, `toBoolean`, `parse(` inside readers and action bodies.
11. **Business identifiers** (feeds `identifiers.md`). List every domain identifier: entity references such as scheme, case, account or order numbers; tax and party IDs (NINO, UTR, CRN, VAT, PAYE, EORI); user and enrolment IDs; and technical keys such as cache ids, composite keys, lock keys and correlation IDs. For each one, record:
    - what it identifies and who issues it
    - every way it enters the service: auth retrievals (trusted), and path, header, query, body or callback (untrusted)
    - every use: URLs, DB keys and indexes, auth decisions, audit events, outbound payload field names
    - its lifecycle and transformations: normalisation, frontend key ↔ upstream key mapping, derivation from another ID
    - its validation rules from three sources, compared: **local** checks (binders, regexes, normalisers), **library** checks (e.g. domain wrapper types that `require` a regex — inspect the jar with `javap -c -constants` if no source is available), and **contract** patterns (bundled JSON/OpenAPI schemas, even unused ones — extract them with a short script)

    Flag mismatches between the three sources, identifiers taken from headers where the auth identity should be used, identifiers that are authorised in one place but read from another, constructor `require`s that turn bad input into 500s, and unencoded interpolation into URLs.

Use `grep` and `sed` over the source with comment and import lines stripped, so you read only the code that matters. Read every connector in full; skim models.

## Step 2 – Write `service.md` (generic summary)

Describe the service in **domain-generic, business-level terms**: what it does and for whom, not how the code is organised. Keep class names out of the summary. Structure:

- `# <Service Name> – Summary`
- **Purpose**: 1–2 paragraphs covering the domain role, who calls it (frontend or other services), and whether it has a UI.
- **Main Capabilities**: numbered subsections grouped by business capability, such as onboarding/registration, profile management, collaboration, offboarding, caching of journey state, and notifications. Under each, give bullets describing the behaviour and its notable business rules.
- **Cross-cutting Concerns**: authentication and authorisation, auditing, validation and transformation, data protection, and feature toggles.
- **Dependencies (generic)**: a small table of the kinds of dependency and their role.
- **In One Sentence**: a one-line elevator summary.

## Step 3 – Write `dependencies.md` (technical detail)

- An intro that explains the shared mechanism: the HTTP client and how base URLs and paths are resolved from config.
- An **Overview table** with these columns: #, Dependency, Type, Config key, Accessed via (class names).
- **One section per dependency**, containing:
  - the base URL source and its local default
  - the headers and auth scheme
  - a table of operations: Operation | Method & path | Code (`Class.method`) | Notes or validation
  - usage notes: callers, error-code mapping, caching or eviction, feature-flag routing, and audit events sent
- **Datastore section**: a table with Collection or table | Repository | Key | Expiry | Purpose, plus how encryption works.
- **Auth section**: a table of the auth actions or guards, what each requires, and what each retrieves.
- **Inbound callers and callbacks**, including webhooks that the service registers with other systems.
- **Libraries** that back these integrations, with versions.
- **Local development**: what the dependencies point to locally (stubs, service-manager profiles).

## Step 4 – Write `validation.md` (data validation patterns)

- `# <Service Name> – Data Validation`, followed by a short paragraph that sums up the overall approach (for example "structural, not semantic": the code checks presence and types, and leaves formats to the upstream system).
- **Validation layers at a glance**: a table with columns #, Layer, Mechanism, Where (classes), On failure (HTTP status or behaviour).
- **Route and path parameters**: a table with columns Parameter | Rule | Code.
- **Request headers**: a table with columns Endpoint | Headers | Validation.
- **Request bodies**: for each flow, give the reader or schema used and the error message returned. Then cover three things:
  - what *is* checked: required fields, types, conditional requirements
  - what is *not* checked: formats, lengths, cross-field rules, counts
  - a table of normalisation and derivation rules
- **External validation services**: the request, the decision rule, and fail-open or fail-closed behaviour.
- **Outbound payload validation**: when it happens (before sending, or only after an upstream rejection), which schema files are used, how failures are logged (PII masking), and which schema files are unused.
- **Upstream response validation**: a table with columns Response | Validation | Failure result.
- **Inbound callbacks** and **cache/opaque stores**: what they accept.
- **Error mapping summary**: a table with columns Source | Exception/value | HTTP to caller.
- **Recommendations**: a short numbered list based on the observations.

## Step 5 – Write `identifiers.md` (business identifiers)

- `# <Service Name> – Business Identifiers`, followed by an intro that defines the three rule sources (local / library / contract) and any terminology notes, such as synonyms used in the codebase.
- **Summary table**: Identifier | Identifies | Format (contract) | Local validation | Enters via | Main uses.
- **One subsection per key identifier group** (entity/scheme IDs, user/enrolment IDs, party/tax IDs, financial/policy IDs, technical IDs). Each covers lifecycle (issuer, where it appears in responses), trusted vs untrusted sources, uses, validation, and rule mismatches.
- **Party identifiers table**: Identifier | Frontend key(s) | Upstream key (per flow) | Local rule | Contract rule, plus details of any normalisation algorithm.
- **Validation coverage matrix**: Identifier | Format checked locally? | Checked against the authenticated user? | Encoded when put in a URL? (✅ / ⚠️ / ❌).
- **Recommendations**: a short numbered list.
- Never include real identifier values from fixtures, stubs or logs. Use patterns and examples of the format only.

## Step 6 – Write `openapi.json` + `openapi.md` (HTTP API)

Don't hand-write the spec. Build it with the bundled generator `scripts/gen_openapi.py`, which lives next to this file (`~/.claude/skills/service-docs/scripts/gen_openapi.py`). Its docstring documents the input format in full.

1. **Write the endpoint table** as `endpoints.json` in the scratchpad directory, not in the repo. It holds one entry per route: `method`, `path` (OpenAPI `{param}` style), `operationId` (the controller method name, made unique), `tag` (business capability), `summary`, `params`, `headers`, `body`, and optionally `responses`, `auth`, `notes` and `downstream`.
   - Use the parameter DSL, `KIND:name[:type][=default][|description]`:
     - `p` is a path parameter, `q` a required query parameter, `q?` an optional one and `q*` a repeatable one.
     - `h` and `h?` are a required and an optional header.
     - `q~` means any query parameters are passed through.
     - Types are `string`, `int`, `long`, `number`, `boolean`, and `multi` for a path parameter that spans several segments.
     - A parameter can also be a raw OpenAPI object.
   - Map framework semantics faithfully. In Play, a route parameter of `Int`/`String` with no `?=` default is required, `Option[...]` is optional, `Seq[...]` is repeatable, and `$x<.+>` is `multi`. Path parameters declared only in the route are still path parameters.
   - `body` is `json`, `none`, `text`, `binary`, or an object `{contentType, schema, description}`. Use the real request schema when the service parses the body into a model, for example by deriving it from the Play JSON `Reads` or the case class. Use free-form JSON only when the service forwards the body without reading it.
   - Put the shared response shapes in `components.responses` and `components.schemas`. Put the statuses that every endpoint can return in `defaultResponses.all`, and those that only body-reading endpoints can return in `defaultResponses.withBody`. An endpoint overrides a default by naming the status in its own `responses`, or removes it by setting it to `null`.
   - Proxies and gateways: set `downstream` on every operation, which becomes the `x-downstream` extension. Set `headersLabel` to `"Forwarded request headers"`.
   - Platform or library routes that are not in the repo's routes files (e.g. bootstrap's `/ping/ping`): include them with `noDefaults: true`.
2. **Generate and check** the spec:
   ```
   python3 -I ~/.claude/skills/service-docs/scripts/gen_openapi.py <scratchpad>/endpoints.json \
     --out openapi.json --md-catalogue <scratchpad>/catalogue.md --routes conf/prod.routes
   ```
   `--routes` takes the top-level Play router named by `play.http.router` in `application.conf`, and follows `->` includes found next to it. Leave it out for non-Play services. The script fails if:
   - an `operationId` is duplicated
   - path parameters don't match the path template
   - a `$ref` doesn't resolve
   - a route is in the routes files but undocumented

   Routes that are documented but missing from the routes files are reported as notes. Fix the table and rerun until the script passes. Don't run external linters such as `npx @redocly/cli` without asking.
3. **Write `openapi.md`**:
   - `# <Service Name> – HTTP API`: one paragraph that links to `openapi.json` and says how the spec was derived (sources, operation and path counts).
   - **Conventions that apply to every endpoint**: a table covering authentication, request body parsing, parameter binding (what makes a request fail with 400 before the controller runs), response pass-through or mapping, the error-status mapping, size limits and auditing.
   - **Access-controlled endpoints**: a table with columns Endpoint | Check | Failure (status and body).
   - Include where relevant: routing or feature-flag tables, a **Forwarded request headers** table (Header | Endpoints), and the **Back-end services** list.
   - **Endpoints with non-standard behaviour**: one bullet per endpoint that departs from the conventions. Examples: a method or path rewritten upstream, raw or binary bodies, streaming, headers copied back, unencoded query values, and route-ordering shadowing.
   - **Endpoint catalogue**: paste the generated `catalogue.md`. It has one table per tag, and adds Auth and Back-end columns when the endpoints set `auth` and `downstream`.
4. Before you finish, trace every documented non-default status back to code that can actually return it, not just to a test that mocks it. Mark statuses that are reachable only in theory as such, in both the spec's response description and `openapi.md`.

## Rules

- Every claim must come from code or config you actually read. Do not guess at endpoints or behaviour.
- Never copy secret values (tokens, keys, client secrets) into the documents. Refer to their config keys instead.
- Point out anomalies you notice while reading, with a ⚠️ **Observation:** prefix. Examples: values computed once when they should be computed per request, connectors calling a different backend than their name suggests, unauthenticated inbound endpoints. Document them; don't fix them unless asked.
- Match the depth to the codebase. Use tables for anything enumerable and prose for rules and flows.
- For validation, verify each failure-status claim by tracing the code path (is it inside the guarded `Future`? does the action have `recoverWith`?). Don't infer it from the exception type alone.
- When you finish, give the user a short summary: what each file covers, plus any observations worth acting on.
