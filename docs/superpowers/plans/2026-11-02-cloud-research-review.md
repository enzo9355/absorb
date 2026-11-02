# Cloud daily research publication plan

> Execution: use superpowers:executing-plans inline. The user has authorized daily AI source review and publication and clarified that fetched data must update the website automatically. Existing authorization covers this repair and its deployment.

**Goal:** Cloud Scheduler's existing 08:00 job fetches sources, checks original material with AI, and publishes eligible summaries without a running personal computer.

**Design:** Extend `research_refresh_cli.run_once` with an optional bounded cloud reviewer, then use existing `publish_review` and public metadata publishing. Source/author/date validation and listed-security membership are deterministic; AI writes an attributed summary and a second check rejects unsupported claims. No source text, candidate fields or model reasoning is public. Original dates are retained; no approved additions means no artificial reviewed timestamp advance. Videos without transcripts, unsupported identities and inaccessible pages remain pending.

**Tech:** Existing Python requests/BeautifulSoup, Gemini 2.5 Flash via existing credentials, official Nasdaq directory reader, GCS CAS publisher. Maximum 20 candidates and 450 seconds per execution; API timeout/quota errors fail closed. No new paid data vendor or dependency. Existing model usage may consume its configured quota; no upgrade is authorized.

**Scope:** New `stock_papi/services/research_ai_review.py` and focused tests; small integration in `stock_papi/batch/research_refresh_cli.py`; operator doc replacing local automation instructions. Website is already able to read independent published catalogs, so no website deployment or traffic switch is needed.

- [ ] Tests first: original source identity/date, unsafe redirects, unknown symbol, unsupported evidence, model rejection/failure, idempotency, metadata updated to newly published version.
- [ ] Implement bounded reviewer, private evidence/checkpoints, existing CAS publication and after-publication readback.
- [ ] Run related regression tests and read-only live review; inspect generated summaries before enabling publication.
- [ ] Build and protect image; grant job service account access only to the existing Gemini secret and bind it to the job. Preserve scheduler, bucket IAM and service traffic.
- [ ] Run cloud job to completion, inspect private review decisions/public object hashes/page contents, prove repeat execution does not duplicate records.
- [ ] Delete local `absorb-ai` automation only once cloud verification succeeds. Record natural-schedule proof separately.

Review focus: HTTP 200 challenge pages; missing/bad source dates; model prompt injection in external content; shared bucket concurrent publisher; public metadata still referring to old reviewed catalog after publication.

Ruling: reuse the existing job rather than a second cloud scheduler so publication follows actual acquisition completion. Preserve unreviewed candidates and existing timestamps on every failure.
