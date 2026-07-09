"""Fetch CHI licensed insurance companies into the Saudi payer registry.

Run manually when network access to chi.gov.sa is available:

    python scripts/fetch_chi_payers.py
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SOURCE_URL = "https://www.chi.gov.sa/en/MarketSectors/Pages/InsuranceCompanies.aspx"
OUTPUT = Path(__file__).resolve().parents[1] / "config/regions/sa/payers/ksa_chi_payers.json"
LINK_PATTERN = re.compile(r"<a[^>]+href=\"([^\"]+)\"[^>]*>([^<]+)</a>", re.IGNORECASE)


def fetch_records() -> list[dict[str, str]]:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "MedexaDataBot/1.0"})
    html = urllib.request.urlopen(request, timeout=60).read().decode("utf-8", errors="replace")
    records: list[dict[str, str]] = []
    for href, label in LINK_PATTERN.findall(html):
        name = re.sub(r"\s+", " ", label).strip()
        if len(name) < 3:
            continue
        if "insurance" not in name.lower() and "tpa" not in name.lower():
            continue
        records.append(
            {
                "payer_name": name,
                "source_url": href if href.startswith("http") else f"https://www.chi.gov.sa{href}",
            }
        )
    deduped = {item["payer_name"]: item for item in records}
    return list(deduped.values())


def main() -> int:
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload: dict[str, object] = {
        "source_name": "CHI Insurance Companies Directory",
        "source_url": SOURCE_URL,
        "version": "1.0.0",
        "fetched_at": fetched_at,
        "classification": "OFFICIAL_PUBLIC",
        "fetch_status": "ok",
        "last_error": None,
        "records": [],
    }
    try:
        payload["records"] = fetch_records()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        payload["fetch_status"] = "failed"
        payload["last_error"] = str(exc)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {OUTPUT} with {len(payload['records'])} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
