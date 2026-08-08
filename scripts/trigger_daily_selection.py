"""Trigger the deployed xuangu API from GitHub Actions or a local shell."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    backend_url = os.environ.get("BACKEND_URL", "").strip().rstrip("/")
    token = os.environ.get("JOB_API_TOKEN", "").strip()
    trade_date = os.environ.get("TRADE_DATE", "").strip()
    if not backend_url or not token:
        print("BACKEND_URL and JOB_API_TOKEN are required", file=sys.stderr)
        return 2

    payload = {"trade_date": trade_date} if trade_date else {}
    request = Request(
        f"{backend_url}/api/selections/run",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Job-Token": token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            body = response.read().decode("utf-8")
            print(body)
            return 0 if response.status == 202 else 1
    except HTTPError as exc:
        print(f"API returned HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
    except URLError as exc:
        print(f"Could not reach backend: {exc.reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
