"""Build NPHIES-compliant professional claim and prior-auth bundle skeletons."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "config" / "regions" / "sa" / "fhir" / "templates"

CLAIM_JSONC = Path(r"c:\Users\AST User\Downloads\professional-claim-bundle-skeleton 1.jsonc")
PRIORAUTH_JSONC = Path(r"c:\Users\AST User\Downloads\professional-priorauth-bundle-skeleton 1.jsonc")

SERVICES = "http://nphies.sa/terminology/CodeSystem/services"
PROCEDURES = "http://nphies.sa/terminology/CodeSystem/procedures"

SUPPORTING_INFO_TEMPLATE = [
    ("vital-sign-systolic", "quantity", "mm[Hg]"),
    ("vital-sign-diastolic", "quantity", "mm[Hg]"),
    ("vital-sign-height", "quantity", "cm"),
    ("vital-sign-weight", "quantity", "kg"),
    ("pulse", "quantity", "/min"),
    ("temperature", "quantity", "Cel"),
    ("chief-complaint", "text", None),
    ("oxygen-saturation", "quantity", "%"),
    ("respiratory-rate", "quantity", "/min"),
    ("patient-history", "string", None),
    ("investigation-result", "investigation", None),
    ("treatment-plan", "string", None),
    ("physical-examination", "string", None),
    ("history-of-present-illness", "string", None),
]

TIMING = {"start": "", "end": ""}


def load_jsonc(path: Path) -> dict:
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "//" not in line:
            lines.append(line)
            continue
        in_string = False
        escaped = False
        cut = len(line)
        for index, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string and line[index : index + 2] == "//":
                cut = index
                break
        lines.append(line[:cut].rstrip())
    return json.loads("\n".join(lines))


def find_claim(bundle: dict) -> dict:
    for entry in bundle["entry"]:
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Claim":
            return resource
    raise ValueError("Claim resource not found")


def find_encounter(bundle: dict) -> dict:
    for entry in bundle["entry"]:
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Encounter":
            return resource
    raise ValueError("Encounter resource not found")


def build_supporting_info() -> list[dict]:
    rows: list[dict] = []
    for seq, (code, kind, unit) in enumerate(SUPPORTING_INFO_TEMPLATE, start=1):
        row: dict = {
            "sequence": seq,
            "category": {
                "coding": [
                    {
                        "system": "http://nphies.sa/terminology/CodeSystem/claim-information-category",
                        "code": code,
                    }
                ]
            },
        }
        if kind == "quantity":
            row["timingPeriod"] = deepcopy(TIMING)
            row["valueQuantity"] = {
                "value": None,
                "system": "http://unitsofmeasure.org",
                "code": unit,
            }
        elif kind == "text":
            row["code"] = {"text": ""}
        elif kind == "string":
            row["valueString"] = ""
        elif kind == "investigation":
            row["code"] = {
                "coding": [
                    {
                        "system": "http://nphies.sa/terminology/CodeSystem/investigation-result",
                        "code": "",
                    }
                ]
            }
        rows.append(row)
    return rows


def set_services_code_system(node: dict) -> None:
    if isinstance(node, dict):
        coding = node.get("coding")
        if isinstance(coding, list):
            for entry in coding:
                if isinstance(entry, dict) and entry.get("system") == PROCEDURES:
                    entry["system"] = SERVICES
        for value in node.values():
            set_services_code_system(value)
    elif isinstance(node, list):
        for item in node:
            set_services_code_system(item)


def patch_claim_bundle(bundle: dict) -> dict:
    out = deepcopy(bundle)
    claim = find_claim(out)
    encounter = find_encounter(out)

    claim.setdefault("extension", [])
    extensions = {ext["url"]: ext for ext in claim["extension"]}

    if "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-encounter" not in extensions:
        claim["extension"].insert(
            0,
            {
                "url": "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-encounter",
                "valueReference": {"reference": ""},
            },
        )

    if "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-episode" not in extensions:
        claim["extension"].append(
            {
                "url": "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-episode",
                "valueIdentifier": {"system": "", "value": ""},
            }
        )

    claim["subType"] = {
        "coding": [
            {
                "system": "http://nphies.sa/terminology/CodeSystem/claim-subtype",
                "code": "op",
                "display": "Outpatient",
            }
        ]
    }
    claim["supportingInfo"] = build_supporting_info()

    for team in claim.get("careTeam", []):
        role = team.get("role", {}).get("coding", [{}])[0]
        if not role.get("code"):
            role["code"] = "primary"
            role["display"] = "Primary provider"

    item = claim["item"][0]
    item_ext = {ext["url"]: ext for ext in item.get("extension", [])}

    def ensure_item_ext(url: str, body: dict) -> None:
        if url not in item_ext:
            item.setdefault("extension", []).append({"url": url, **body})

    ensure_item_ext(
        "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-patient-share",
        {"valueMoney": {"value": None, "currency": "SAR"}},
    )
    ensure_item_ext(
        "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-package",
        {"valueBoolean": False},
    )
    ensure_item_ext(
        "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-maternity",
        {"valueBoolean": False},
    )
    ensure_item_ext(
        "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-patientInvoice",
        {"valueIdentifier": {"system": "", "value": ""}},
    )

    for ext in item["extension"]:
        if ext["url"].endswith("extension-package"):
            ext["valueBoolean"] = False
        if ext["url"].endswith("extension-maternity"):
            ext["valueBoolean"] = False
        if ext["url"].endswith("extension-patient-share"):
            ext["valueMoney"]["value"] = None
        if ext["url"].endswith("extension-tax"):
            ext["valueMoney"]["value"] = None

    item["informationSequence"] = list(range(1, 15))
    item["productOrService"]["coding"][0]["system"] = SERVICES
    item["unitPrice"]["value"] = None
    item["net"]["value"] = None
    claim["total"]["value"] = None

    encounter["meta"]["profile"] = [
        "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/encounter-claim-AMB|1.0.0"
    ]
    encounter["extension"] = [
        {
            "url": "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-serviceEventType",
            "valueCodeableConcept": {
                "coding": [
                    {
                        "system": "http://nphies.sa/terminology/CodeSystem/service-event-type",
                        "code": "ICSE",
                        "display": "Initial client service event",
                    }
                ]
            },
        }
    ]
    encounter["status"] = "finished"
    encounter["class"] = {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": "AMB",
        "display": "Ambulatory",
    }
    encounter["serviceType"] = {
        "coding": [
            {
                "system": "http://nphies.sa/terminology/CodeSystem/service-type",
                "code": "rehabilitation",
                "display": "Rehabilitation",
            }
        ]
    }
    encounter["priority"] = {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
                "code": "EL",
                "display": "Elective",
            }
        ]
    }

    set_services_code_system(out)
    return out


def patch_priorauth_bundle(bundle: dict) -> dict:
    out = deepcopy(bundle)
    claim = find_claim(out)
    encounter = find_encounter(out)

    claim["subType"] = {
        "coding": [
            {
                "system": "http://nphies.sa/terminology/CodeSystem/claim-subtype",
                "code": "op",
                "display": "Outpatient",
            }
        ]
    }
    claim["priority"] = {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/processpriority",
                "code": "normal",
                "display": "Normal",
            }
        ]
    }

    for team in claim.get("careTeam", []):
        role = team.get("role", {}).get("coding", [{}])[0]
        if not role.get("code"):
            role["code"] = "primary"
            role["display"] = "Primary provider"

    item = claim["item"][0]
    for ext in item["extension"]:
        if ext["url"].endswith("extension-package"):
            ext["valueBoolean"] = False
        if ext["url"].endswith("extension-maternity"):
            ext["valueBoolean"] = False
        if ext["url"].endswith("extension-patient-share"):
            ext["valueMoney"]["value"] = None

    item["informationSequence"] = list(range(1, 15))
    item["productOrService"]["coding"][0]["system"] = SERVICES
    item["unitPrice"]["value"] = None
    item["net"]["value"] = None
    claim["total"]["value"] = None

    encounter["meta"]["profile"] = [
        "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/encounter-auth-AMB|1.0.0"
    ]
    encounter["extension"] = [
        {
            "url": "http://nphies.sa/fhir/ksa/nphies-fs/StructureDefinition/extension-serviceEventType",
            "valueCodeableConcept": {
                "coding": [
                    {
                        "system": "http://nphies.sa/terminology/CodeSystem/service-event-type",
                        "code": "ICSE",
                        "display": "Initial client service event",
                    }
                ]
            },
        }
    ]
    encounter["status"] = "in-progress"
    encounter["class"] = {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": "AMB",
        "display": "Ambulatory",
    }
    encounter["serviceType"] = {
        "coding": [
            {
                "system": "http://nphies.sa/terminology/CodeSystem/service-type",
                "code": "rehabilitation",
                "display": "Rehabilitation",
            }
        ]
    }
    encounter["priority"] = {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
                "code": "EL",
                "display": "Elective",
            }
        ]
    }
    if "end" in encounter.get("period", {}):
        del encounter["period"]["end"]

    set_services_code_system(out)
    return out


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    claim = patch_claim_bundle(load_jsonc(CLAIM_JSONC))
    priorauth = patch_priorauth_bundle(load_jsonc(PRIORAUTH_JSONC))

    claim_json = OUT_DIR / "claim-request.template.json"
    priorauth_json = OUT_DIR / "priorauth-request.template.json"

    write_json(claim_json, claim)
    write_json(priorauth_json, priorauth)
    write_json(CLAIM_JSONC, claim)
    write_json(PRIORAUTH_JSONC, priorauth)

    claim_text = claim_json.read_text(encoding="utf-8")
    priorauth_text = priorauth_json.read_text(encoding="utf-8")

    assert "extension-episode" in claim_text
    assert "extension-patientInvoice" in claim_text
    assert "extension-maternity" in claim_text
    assert claim_text.count("claim-information-category") >= 14
    assert "encounter-claim-AMB" in claim_text
    assert PROCEDURES not in claim_text

    assert "extension-eligibility-response" in priorauth_text
    assert '"code": "op"' in priorauth_text
    assert PROCEDURES not in priorauth_text

    print(f"Wrote {claim_json}")
    print(f"Wrote {priorauth_json}")
    print(f"Updated {CLAIM_JSONC}")
    print(f"Updated {PRIORAUTH_JSONC}")


if __name__ == "__main__":
    main()
