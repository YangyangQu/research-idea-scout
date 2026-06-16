from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from .assets import row_to_asset, write_assets
from .io_utils import read_jsonl


def extract_assets(rows: List[Dict[str, Any]], profile_name: str = "") -> List[Dict[str, Any]]:
    assets = []
    seen = set()
    for row in rows:
        asset = row_to_asset(row, profile_name=profile_name)
        if asset["asset_id"] in seen:
            continue
        seen.add(asset["asset_id"])
        assets.append(asset)
    return assets


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract Insight/Method assets from paper or scored JSONL.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--profile-name", default="")
    args = ap.parse_args()

    rows = list(read_jsonl(args.input))
    assets = extract_assets(rows, profile_name=args.profile_name)
    write_assets(args.output, assets)
    print(json.dumps({"input": args.input, "output": args.output, "assets": len(assets)}, indent=2))


if __name__ == "__main__":
    main()
