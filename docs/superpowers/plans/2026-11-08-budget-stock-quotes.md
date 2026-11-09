# Budget stock quote updates

User delegates implementation decisions and prioritizes minimum spending.

Design: add a separate latest-quote card to normal individual stock pages. Fetch on opening, then every 60 seconds while visible; slow to 15 minutes outside regular weekday sessions, stop when hidden/offline, and back off five minutes on failure. Keep verified closing prices, charts, predictions and calculations unchanged. Reuse the existing Yahoo chart source with a lightweight metadata-only adapter, no paid subscription, background job, persistent connection, new infrastructure or dependency. Show the source timestamp and possible delay explicitly.

Alternatives considered: streaming keeps Cloud Run active; TradingView's free widget does not list TWSE coverage; periodic on-demand requests cover the existing TW/US symbols consistently. Yahoo redistribution rights are not established by existing use: local implementation and tests do not establish permission for public deployment.

Scope: new stock_quote service and tests; market route and route inventory; stock_detail template; page-only JavaScript and its asset version; browser/controller checks. Preserve existing uncommitted work.

- [x] Test quote validation, TWSE/TPEx/US mapping, cache reuse/expiry, failure backoff, bounded concurrency, market hours and timestamp safety.
- [x] Implement the adapter and lightweight endpoint without running analysis or reading snapshots on refresh.
- [x] Test and implement visible-only refresh, retained last quote on failure, pause/resume and response validation; requests have an 8-second browser timeout and 4-second upstream socket timeout.
- [x] Verify route/template/security regressions and representative source responses. Review the exact task diff.

Limits: cache and upstream request cap are per Python process; no claim of global deduplication. No paid plan or production deployment is authorized by this document. Quote coverage and provider delay are external dependencies.

Review: independent reviewer identified cache hits blocked by unrelated upstream fetches (P2), and resumed pages incorrectly continuing to say paused (P3). The latter was treated as a correctness issue because the misleading status can persist for 15 minutes. Both received reproducing failing tests and fixes. Cache reads now use a separate short-held lock; the displayed active status is restored on resume. No deferred findings.

Validation: 99 focused Python tests passed, Node controller self-check passed, Edge desktop (1440px) and mobile (390px) fixture checks passed including failed refresh retention. Four real Yahoo probes succeeded: 2330.TW, 6488.TWO, AAPL, BRK-B. It was Sunday, so continuous in-session price movement was not observed. No production deploy or new cloud resource.

Push preparation (2026-11-10): isolated only this feature onto origin/main at 8f42b93. Adapted asset hashing and the route test fixture to that branch's existing interfaces. All 134 focused Python tests and the Node controller checks passed in the isolated checkout. Push targets a feature branch; main's automatic deployment is not triggered. The original working directory is preserved.
