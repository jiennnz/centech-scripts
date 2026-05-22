from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SideInputConfig:
    """One side of the comparison (CenTech system export or client/GL export)."""

    format: str  # "csv" | "excel"
    date_column: str
    store_column: str
    category_column: str
    debit_column: str
    credit_column: str
    date_parse_format: str | None
    skip_category: str | None
    skip_zero_debit_credit: bool
    category_rewrites: dict[str, str]
    memo_column: str | None
    online_credit_card: dict[str, Any] | None
    store_parse: str  # "strip" | "first_token"
    round_debit_credit_for_categories: frozenset[str]
    category_starts_with: dict[str, str]
    read_csv_kwargs: dict[str, Any] = field(default_factory=dict)
    read_excel_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrgRule:
    org_key: str
    org_display_name: str
    """Label for Excel columns D/E (client / GL data). CenTech stays B/C."""
    client_header_label: str
    stores: list[str]
    sheet_date_format: str
    category_rows: dict[str, int]
    centech: SideInputConfig
    client: SideInputConfig
    mismatch_tolerance: float
    ignored_categories: frozenset[str] = field(default_factory=frozenset)
    qa: SideInputConfig | None = None


def available_orgs(rules_dir: Path) -> list[str]:
    return sorted(path.stem for path in rules_dir.glob("*.yaml"))


def _side(payload: dict[str, Any], *, label: str) -> SideInputConfig:
    fmt = (payload.get("format") or "csv").lower()
    if fmt not in {"csv", "excel"}:
        raise ValueError(f"{label}: format must be 'csv' or 'excel', got {fmt!r}")

    required = ["date_column", "store_column", "category_column", "debit_column", "credit_column"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"{label}: missing fields: {missing}")

    occ = payload.get("online_credit_card")
    if occ is not None and not isinstance(occ, dict):
        raise ValueError(f"{label}: online_credit_card must be a mapping or omitted")

    store_parse = (payload.get("store_parse") or "strip").lower()
    if store_parse not in {"strip", "first_token"}:
        raise ValueError(f"{label}: store_parse must be 'strip' or 'first_token'")

    round_list = payload.get("round_debit_credit_for_categories") or []
    round_set = frozenset(str(x).strip() for x in round_list if str(x).strip())

    csw = payload.get("category_starts_with") or {}
    if not isinstance(csw, dict):
        raise ValueError(f"{label}: category_starts_with must be a mapping")
    category_starts_with = {str(k).lower(): str(v) for k, v in csw.items()}

    rewrites = payload.get("category_rewrites") or {}
    if not isinstance(rewrites, dict):
        raise ValueError(f"{label}: category_rewrites must be a mapping")

    read_csv = dict(payload.get("read_csv") or {})
    read_excel = dict(payload.get("read_excel") or {})

    return SideInputConfig(
        format=fmt,
        date_column=str(payload["date_column"]),
        store_column=str(payload["store_column"]),
        category_column=str(payload["category_column"]),
        debit_column=str(payload["debit_column"]),
        credit_column=str(payload["credit_column"]),
        date_parse_format=payload.get("date_parse_format"),
        skip_category=(str(payload["skip_category"]).strip() if payload.get("skip_category") else None),
        skip_zero_debit_credit=bool(payload.get("skip_zero_debit_credit", True)),
        category_rewrites={str(k): str(v) for k, v in rewrites.items()},
        memo_column=str(payload["memo_column"]).strip() if payload.get("memo_column") else None,
        online_credit_card=occ,
        store_parse=store_parse,
        round_debit_credit_for_categories=round_set,
        category_starts_with=category_starts_with,
        read_csv_kwargs=read_csv,
        read_excel_kwargs=read_excel,
    )


def load_org_rule(org_key: str, rules_dir: Path) -> OrgRule:
    path = rules_dir / f"{org_key}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Rule file not found: {path}")

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    stores = [str(s).strip() for s in payload.get("stores", []) if str(s).strip()]
    if not stores:
        raise ValueError(f"No stores configured in {path.name}")

    centech_raw = payload.get("centech") or payload.get("input", {}).get("centech")
    client_raw = payload.get("client") or payload.get("input", {}).get("source")
    if not isinstance(centech_raw, dict):
        raise ValueError(f"{path.name}: missing 'centech' input block")
    if not isinstance(client_raw, dict):
        raise ValueError(f"{path.name}: missing 'client' input block")

    qa_raw = payload.get("qa")
    qa_config: SideInputConfig | None = None
    if isinstance(qa_raw, dict):
        qa_config = _side(qa_raw, label=f"{path.name} qa")

    category_rows_raw = payload.get("category_rows") or {}
    if not isinstance(category_rows_raw, dict):
        raise ValueError(f"{path.name}: category_rows must be a mapping")
    category_rows = {str(k): int(v) for k, v in category_rows_raw.items()}

    ignored_raw = payload.get("ignored_categories") or []
    if not isinstance(ignored_raw, list):
        raise ValueError(f"{path.name}: ignored_categories must be a list")
    ignored_categories: frozenset[str] = frozenset(str(x).strip() for x in ignored_raw if str(x).strip())

    client_header = (
        payload.get("client_header_label")
        or payload.get("source_label")
        or "Client"
    )

    return OrgRule(
        org_key=str(payload.get("org_key", org_key)),
        org_display_name=str(payload.get("org_display_name", org_key)),
        client_header_label=str(client_header),
        stores=stores,
        sheet_date_format=str(payload.get("sheet_date_format", "%b %d")),
        category_rows=category_rows,
        centech=_side(centech_raw, label=f"{path.name} centech"),
        client=_side(client_raw, label=f"{path.name} client"),
        mismatch_tolerance=float(payload.get("mismatch_tolerance", 0.0)),
        ignored_categories=ignored_categories,
        qa=qa_config,
    )
