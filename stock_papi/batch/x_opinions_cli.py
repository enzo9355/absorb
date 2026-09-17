"""Fetch an X user timeline into a manual-review candidate catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from stock_papi.services.x_api import XApiClient, XApiConfig, XApiError, build_pending_candidate
from stock_papi.services.fx_twitter import FxTwitterClient


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch one X timeline into a pending ABSORB catalog")
    parser.add_argument("--username", required=True, help="X username without @")
    parser.add_argument("--creator-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--market", choices=("TW", "US"))
    parser.add_argument("--symbol")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--provider", choices=("fxtwitter", "x-api"), default="fxtwitter",
                        help="Default: credential-free FxTwitter; x-api is an explicit potentially billable opt-in")
    args = parser.parse_args(argv)
    try:
        public_catalog = Path(__file__).resolve().parents[2] / "data" / "research" / "public-opinions.json"
        if args.output.resolve() == public_catalog.resolve():
            raise ValueError("candidate output must not overwrite the public catalog")
        previous = {}
        if args.output.exists():
            if args.output.stat().st_size > 2_000_000:
                raise ValueError("existing candidate exceeds size limit")
            prior = json.loads(args.output.read_text(encoding="utf-8"))
            if not isinstance(prior, dict) or not isinstance(prior.get("opinions"), list):
                raise ValueError("existing candidate is invalid; refusing to overwrite")
            previous = {row.get("opinion_id"): row for row in prior["opinions"] if isinstance(row, dict)}
        client = FxTwitterClient() if args.provider == "fxtwitter" else XApiClient(XApiConfig.from_environment())
        result = client.fetch_user_posts(
            args.username,
            start_time=args.start_time,
            end_time=args.end_time,
            max_pages=args.max_pages if args.max_pages is not None else (3 if args.provider == "fxtwitter" else client.config.max_pages),
        )
        candidate = build_pending_candidate(
            result,
            creator_id=args.creator_id,
            market=args.market,
            symbol=args.symbol,
        )
        for row in candidate["opinions"]:
            old = previous.get(row["opinion_id"], {})
            if old.get("raw_payload_sha256") == row["raw_payload_sha256"] and old.get("creator_id") == row["creator_id"]:
                row["first_seen_at"] = old.get("first_seen_at") or row["first_seen_at"]
        _write_json(args.output, candidate)
    except (XApiError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output),
                "username": args.username.lstrip("@"),
                "posts": len(candidate["opinions"]),
                "status": "pending_review",
                "provider": args.provider,
                "has_more": candidate["fetch_meta"]["has_more"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
