# X Opinion Source Feasibility — C1 / API connector

Update 2026-09-18: the earlier retrieval blocker below is superseded for free candidate ingestion. FxTwitter is now the default provider and the local watcher polls every five minutes. Six posts were manually reviewed and promoted to catalog version `public-opinions-v2-c2-2026-09-18-x-review`; the remaining candidates stay pending. See [free ingestion](fxtwitter-ingestion.md). The local watcher is separate from Cloud Run deployment.

Checked at: 2026-09-17T12:00:00+08:00; connector implementation checked at 2026-09-17  
Reviewer: codex  
Scope: C1 source/account feasibility, v2 catalog contract and official API connector. Browser scraping remains disabled; no full-text republication or performance claims.

## Summary

| Creator | Catalog ID | Status | Result |
|---|---|---|---|
| Unusual Whales | `unusual-whales` | `partial` | Profile, six-source review sample and two confirmed news-relay rows are available; remaining candidate posts are not reviewed. |
| Serenity / @aleabitoreddit | `candidate_serenity` | `partial` | Official oEmbed author binding and two confirmed 3006 opinion rows are available; handle identity is verified for this catalog, while legal identity and remaining posts stay out of scope. |
| Michael Sikand | `michael-sikand` | `partial` | Profile, six-source review sample and two confirmed opinion rows are available; remaining candidate posts are not reviewed. |
| Alpha Consensus / Capafy | reference only | `reference` | Product reference for workflow shape only; it is not a creator, source of original posts, or consensus denominator. |

## Account Checks

### Unusual Whales

- `creator_id`: `unusual-whales`
- Canonical profile URL: `https://x.com/unusual_whales`
- Official site checked: `https://unusualwhales.com/`
- Acquisition result: the free FxTwitter timeline and official X oEmbed author URL matched two reviewed post permalinks.
- Sample window: 2026-09-16 to 2026-09-17.
- Verified post count: 2; both are news relay summaries and do not count as investment recommendations.
- `last_success_at`: 2026-09-17T17:03:31.082883Z.
- Status: `partial`.
- C1 ruling: keep creator and coverage metadata; do not create confirmed opinions until a permalink with immutable post ID, timestamp, timezone, review state and rights note is available.

### Serenity

- `creator_id`: `candidate_serenity`
- Canonical profile URL: `https://x.com/aleabitoreddit`
- Discovery references checked: `https://www.trackserenity.com/`, `https://semiconstocks.com/`, Capafy/Lucas publisher page.
- Acquisition result: the free FxTwitter timeline and official X oEmbed author URL matched two original post permalinks.
- Sample window: 2026-09-08 to 2026-09-14.
- Verified post count: 2; both are bullish mention summaries for TW 3006, with disclosed holdings preserved as metadata.
- `last_success_at`: 2026-09-17T17:03:36.078621Z.
- Status: `partial`.
- C1 ruling: keep the stable `candidate_serenity` ID and handle binding; do not infer a legal identity or promote remaining candidate posts.

### Michael Sikand

- `creator_id`: `michael-sikand`
- Canonical profile URL: `https://x.com/michaelsikand`
- Official site checked: `https://sikandmedia.com/`
- Acquisition result: the free FxTwitter timeline and official X oEmbed author URL matched two reviewed post permalinks.
- Sample window: 2026-09-11 to 2026-09-15.
- Verified post count: 2; one META and one SONY bullish mention summary.
- `last_success_at`: 2026-09-17T17:03:40.847201Z.
- Status: `partial`.
- C1 ruling: keep creator and coverage metadata; separate future statements, disclosed holdings and explicit recommendations in v2 fields. Remaining candidates stay pending.

### Alpha Consensus / Capafy

- Reference URL: `https://capafy.ai/agent/alpha-consensus-x-s-best-traders/2987621471?languageCode=en`
- Publisher reference: `https://capafy.ai/publisher/Lucas`
- Status: `reference`.
- C1 ruling: preserve as product reference only. Do not copy its database, summaries, rankings, claimed update frequency or creator denominator into ABSORB.

## Contract Notes

- Confirmed v2 opinions require `source_url`, canonical `source_id`, timezone-bearing `published_at`, `first_seen_at` and `reviewed_at`, `review_status=confirmed`, `source_status=available`, valid `content_type`, valid `stance`, valid `recommendation_kind`, and either a verified `market + symbol` or a company-level record.
- X post sources accept only HTTPS `x.com/<handle>/status/<post_id>` or equivalent `twitter.com` status URLs. Query strings and fragments are removed before storage.
- `youtube_video`, `official_site`, `article` and `video` sources can be preserved by the validator, but pending or legacy records stay out of confirmed consensus and outcome samples.
- Existing YouTube v1 records keep their stable IDs in `data/research/public-opinions.json`, with `review_status=legacy_unverified` and `source_status=pending_review`.
- Unknown market/symbol, missing timezone, unreviewed records, unavailable sources and duplicate immutable source IDs are retained with validation errors and `is_confirmed=false`.
