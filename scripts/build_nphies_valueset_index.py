"""Build a verified NPHIES FHIR ValueSet index from public IG HTML pages.

Only codes present in the official expansion tables are included. This script
does not invent terminology records.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASE_URL = "https://portal.nphies.sa/ig"
VALUESET_SLUGS = [
    "ValueSet-claim-type",
    "ValueSet-claim-subtype",
    "ValueSet-message-events",
    "ValueSet-diagnosis-type",
    "ValueSet-coverage-type-sa",
    "ValueSet-ksa-identifier-patient",
    "ValueSet-adjudication-error",
    "ValueSet-claim-processing-outcome",
]

ROW_PATTERN = re.compile(
    r"<code>([^<]+)</code></td><td[^>]*>.*?>([^<]+)</a></td><td>([^<]+)</td>",
    re.DOTALL,
)


def fetch_html(slug: str) -> str:
    url = f"{BASE_URL}/{slug}.html"
    request = urllib.request.Request(url, headers={"User-Agent": "MedexaDataBot/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_expansion(html: str, slug: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if "Expansion" not in html:
        return records
    for system, code, display in ROW_PATTERN.findall(html):
        code = code.strip()
        display = display.strip()
        if code.lower() in {"code", "system", "---"}:
            continue
        if not system.startswith("http"):
            continue
        records.append(
            {
                "valueset_slug": slug,
                "system": system.strip(),
                "code": code,
                "display": display,
            }
        )
    return records


def build_index() -> dict[str, object]:
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    valuesets: list[dict[str, object]] = []
    all_records: list[dict[str, str]] = []
    for slug in VALUESET_SLUGS:
        entry: dict[str, object] = {
            "slug": slug,
            "source_url": f"{BASE_URL}/{slug}.html",
            "fetch_status": "ok",
            "record_count": 0,
            "error": None,
        }
        try:
            html = fetch_html(slug)
            records = parse_expansion(html, slug)
            entry["record_count"] = len(records)
            all_records.extend(records)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            entry["fetch_status"] = "failed"
            entry["error"] = str(exc)
        valuesets.append(entry)
    return {
        "source_name": "NPHIES Healthcare Financial Services Implementation Guide",
        "source_url": f"{BASE_URL}/artifacts.html",
        "version": "1.0.0",
        "fetched_at": fetched_at,
        "classification": "OFFICIAL_PUBLIC",
        "valuesets": valuesets,
        "records": all_records,
    }


def main() -> int:
    output = Path(__file__).resolve().parents[1] / "config/regions/sa/reference/nphies_fhir_valueset_index.json"
    payload = build_index()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {output} with {len(payload['records'])} terminology records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
