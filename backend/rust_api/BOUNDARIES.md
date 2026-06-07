# Rust API Boundaries

This backend keeps route wiring, job orchestration, query scope checks, and view
projection separate. Keep new code on the narrowest layer that owns the
decision.

## Route Layer

Files under `src/routes/**` should only:

- extract Axum state, headers, path params, query params, and JSON bodies;
- compute HTTP-only context such as `base_url`;
- call `JobsFacade` through response boundary modules;
- wrap results in `ApiResponse`.

Routes should not read job files, inspect artifacts, merge event streams, or
construct view payloads directly.

`src/routes/jobs/json_response/**` is the JSON response boundary for job routes:
it calls `JobsFacade`, computes HTTP-only values such as `base_url`, and wraps
typed views in `ApiResponse`. Axum handlers under `src/routes/jobs/query/**`
should stay focused on extraction and delegation.

`src/routes/download_response/**` is the file response boundary for job-backed
downloads, markdown documents, previews, covers, and thumbnails. Jobs and
library routes may both use it, but routes should not reach into another route
module to reuse a private download helper.

Create routes are the intentional input-side exception: they parse JSON or
multipart request bodies before delegating to `JobsFacade`, then still return a
typed `ApiResponse`.

## API Contract Tests

HTTP-level tests under `src/api_tests/**` guard public route contracts:

- `http_contract.rs` owns the JSON envelope contract for success and common
  error responses.
- `jobs_events/**` owns event stream shape, source merging, and `seq` ordering.
- `jobs_reader/**`, `jobs_retry/**`, and translation debug tests own their
  public endpoint contracts.

Service unit tests should cover internal rules. Avoid mixing service fixtures,
HTTP envelope assertions, and frontend-facing event shape checks into one large
test file.

## Jobs Facade

Files under `src/services/jobs/facade/**` are the boundary for job API use cases.
They decide which service operation to run and return typed views or download
handles.

Facade code may call:

- `services/jobs/query.rs` for loading and scope checks;
- `services/jobs/presentation/**` for public job/list/event view projection;
- `services/jobs/downloads/**`, `reader_regions/**`, `debug/**`, and command
  modules for their specific use cases.

Callers outside `services/jobs/**` should not call presentation internals.

## Query Scope

`src/services/jobs/query.rs` owns job loading and compatibility checks:

- missing job -> `404`;
- OCR-only scope checks;
- legacy layout rejection;
- list filtering before presentation.

Do not put these checks in presentation code. Presentation should receive a job
that has already passed the route/facade scope.

## Presentation

`src/services/jobs/presentation/**` owns view construction for job detail, job
list, events, artifact links, and contracts.

Presentation should not become a general shared utility bucket. Shared data
loading that is needed outside presentation belongs in a sibling module under
`services/jobs/**`.

## Shared Job Projection Helpers

These modules are shared inside the jobs service and, where needed, by sibling
service projections such as `book_projection`:

- `src/services/jobs/live_stage.rs`: combined event loading, canonical event
  projection, and live progress snapshots.
- `src/services/jobs/summary_loaders.rs`: normalized/translation summary file
  readers.

They are intentionally outside `presentation` so library/book projections do not
depend on job view internals.

## Persistence

`src/db/**` should stay focused on SQLite rows and records. It should not know
about HTTP view contracts, route URLs, or frontend display decisions.

## Models

`src/models/**` contains serializable input, job records, and public view types.
Model helpers can build plain data structures, but service decisions such as
file readiness, route scope, and event-source merging should remain in services.
