# Research delivery implementation plan

> Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the approved first three improvements: private daily watchlist digest, an operator review workbench with guarded publication, and announcement classification/correction comparison.

**Architecture:** Extend existing Flask research/account pages and validated catalogs. Keep the production website read-only. A loopback-only operator tool reads private candidates, records explicit review decisions, and publishes reviewed summaries through a separate versioned GCS object with generation preconditions; daily ingestion cannot overwrite reviewed content.

**Tech Stack:** Existing Python/Flask, unittest, Jinja, GCS REST, Cloud Run.

**Spec:** User approved the recommendations in this conversation and explicitly authorized implementation and production publication on 2026-10-04. Scope is the recommended first three features, not new paid APIs, SEC ingestion, or new outbound LINE messages.

## Global constraints
- Start at verified production source 8d1f210 plus documentation 00acc57. Preserve all other checkouts.
- Pending candidates never become confirmed automatically. Operator must supply summary, market, symbol, content type, stance, review identity and rights note.
- Private watchlist digest uses authenticated user's own state, Taipei dates and cutoff-aware reviewed opinions. Unknown/failed coverage is not zero activity.
- Corrections link only an explicit same-company/date/title match or existing correction_of. Ambiguity remains unlinked. Render source text as escaped text.
- Keep event schema and current daily job compatible. Derived labels do not modify original facts.
- No service-account privilege expansion; operator publication uses existing local credentials.
- Candidate deployment, smoke, traffic switch, independent verifier and browser readback required for production claims.

## Review focus
- Cross-user watchlist leakage and cache headers (task 1).
- Midnight Taipei and future review/announcement timestamps (task 1).
- Ambiguous or missing correction targets and long/untrusted text (task 2).
- CSRF, DNS rebinding, private candidate escape and stale publication base (task 3).
- Reviewed object outage/invalid payload and daily refresh compatibility (task 3).

### Task 1: Private daily digest
Files: services/research_digest.py, web/routes/auth.py, web/route_registration.py, templates/account_watchlist.html, tests/test_research_digest.py.
Interface: build_daily_digest(watchlist, events, catalog, *, now, event_status) -> dict with date, announcements, opinions, statuses.
- [ ] Write and run tests for same-day announcements without effective dates, newly reviewed old opinions, future exclusion, TW/US identity and empty watchlist.
- [ ] Implement service, account integration, escaped source-linked cards and no-store route behavior.
- [ ] Run digest/account/research tests; expect PASS; commit.

### Task 2: Announcement classification and correction comparison
Files: services/event_context.py, web/routes/research.py, templates/events.html, tests/test_event_context.py.
Interface: annotate_events(events) -> detached rows with category, correction_notice, correction_original, correction_changes.
- [ ] Write and run tests: unique explicit ROC-date/title match, ambiguous match left unlinked, cross-market/company isolation, source rows unchanged.
- [ ] Add derived filters and escaped original/current comparison, retaining existing event_type filtering.
- [ ] Run event/service/route tests; expect PASS; commit.

### Task 3: Review workbench and guarded publication
Files: repositories/reviewed_opinions.py, batch/research_review_cli.py, services/research_catalog.py, templates/research_review.html, tests/test_research_review.py.
Interfaces: read_reviewed_catalog() -> validated catalog or None; publish_review(store, base, generation, review) -> receipt; create_review_app(catalog, candidates, save_review, token) -> loopback operator Flask app.
- [ ] Write failing tests for pending rejection, generation conflict, public raw-text stripping, reader fallback, host/origin/CSRF rejection and explicit review export.
- [ ] Implement separate public reviewed object, immutable archive and readback, preparation from private cloud candidates, loopback review form and exclusive output.
- [ ] Run review/catalog/refresh tests; expect PASS; commit.

### Task 4: Acceptance and production publication
- [ ] Run whole suite once, record pre-existing failures separately, fix new regressions. Review entire diff with fresh reviewer.
- [ ] Capture LKG, commit and push feature branch, deploy candidate without traffic, smoke and verify.
- [ ] Apply production traffic only after checks, recheck provenance and browser desktop/mobile, record evidence and limitations.

## Execution ledger
- Setup: isolated managed worktree; baseline 14 focused tests PASS. Production 00313-zij at 100%, source 8d1f210.
- Ruling: separate reviewed-opinions object prevents daily ingestion from overwriting operator publication. Review found metadata must also use the current reviewed catalog version; update the existing Job to the website's verified image digest without changing IAM or schedules.
- Ruling: local operator workbench provides the requested review UI while retaining production read-only privileges and requiring no new admin identity configuration.
- Tasks 1-2: complete in ec7fc37; initial digest/event/account/LINE tests 56 PASS.
- Task 3: four independent review findings fixed (source-error visibility, metadata version/pending count, atomic operator checkpoint, private workspace containment). Additional persisted US identity regression fixed using existing symbol validators.
- Full suite before final fixes: 1,880 tests, 3 failures, 2 skipped. Baseline independently reproduces mutex abandonment and US retry-duration mismatch; installer transient Running/Ready race passes isolated on baseline. No scheduler implementation changes.
