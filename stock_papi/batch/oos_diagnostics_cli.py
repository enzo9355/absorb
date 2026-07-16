"""CLI for immutable OOS diagnostics; never promotes a model."""

import argparse
import json
from pathlib import Path

from stock_papi.batch.oos_diagnostics import build_oos_diagnostics


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build immutable ABSORB OOS diagnostics")
    parser.add_argument("--root", type=Path, default=Path(r"D:\AbsorbData"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    args = parser.parse_args(argv)
    if args.root not in {Path(r"D:\AbsorbData"), Path(r"D:\StockPapiData")}:
        raise ValueError("data root is not allowlisted")
    if not 100 <= args.bootstrap_iterations <= 10_000:
        raise ValueError("bootstrap iterations are outside the safe range")
    result = build_oos_diagnostics(
        args.root,
        args.candidate,
        bootstrap_iterations=args.bootstrap_iterations,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
