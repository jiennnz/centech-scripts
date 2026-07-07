from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dateutil import parser as date_parser
from tqdm import tqdm

from financial.sales_export_comparison.rules import available_orgs, load_org_rule
from financial.sales_export_comparison.stages.diagnostics import DiagnosticsConfig
from financial.sales_export_comparison.stages.diagnostics import run as run_diagnostics
from financial.sales_export_comparison.stages.generator import WorkbookFillConfig
from financial.sales_export_comparison.stages.generator import run as run_generator
from financial.sales_export_comparison.stages.heatmap import HeatmapConfig
from financial.sales_export_comparison.stages.heatmap import run as run_heatmap
from financial.sales_export_comparison.stages.template_builder import (
    DEFAULT_LAYOUT,
    build_template_workbook,
)
from financial.sales_export_comparison.stages.verifier import VerifierConfig
from financial.sales_export_comparison.stages.verifier import run as run_verifier

DEFAULT_RULES_DIR = Path(__file__).resolve().parent / "rules"
DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent / "templates" / "Sales_Template.xlsx"
)
DEFAULT_RUNS_ROOT = REPO_ROOT / "financial" / "sales_export_comparison" / "runs"


@dataclass(frozen=True)
class RunConfig:
    start_date: date
    end_date: date
    org_key: str
    source_label: str
    template_path: Path
    rules_dir: Path
    output_dir: Path
    run_mode: str
    centech_csv: Path | None
    source_csv: Path | None
    skip_data: bool
    source_kind: str = "client"
    centech_only: bool = False
    pos_data_dir: Path | None = None
    qa_on_left: bool = False  # QA fills centech slot (QA vs Client)
    centech_label: str = "CenTech"
    include_cross_date_lookahead: bool = True
    pos_source_date: date | None = None
    pos_source_date_from: date | None = None
    pos_source_date_through: date | None = None


def parse_date_flexible(raw: str) -> date:
    try:
        return date_parser.parse(raw, fuzzy=True).date()
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Could not parse date: {raw!r}") from exc


def build_period_key(start_date: date, end_date: date) -> str:
    return f"{start_date.isoformat()}_{end_date.isoformat()}"


def _prompt_date(label: str) -> date:
    while True:
        raw = input(label).strip()
        if not raw:
            print("Input required.")
            continue
        try:
            return parse_date_flexible(raw)
        except ValueError as exc:
            print(exc)


def _prompt_org(rules_dir: Path) -> str:
    orgs = available_orgs(rules_dir)
    if not orgs:
        raise SystemExit(f"No rule files found in: {rules_dir}")

    while True:
        print("\nAvailable organizations:")
        for idx, org in enumerate(orgs, start=1):
            print(f"  {idx}. {org}")
        raw = input("Select org (name or number): ").strip()
        if not raw:
            print("Input required.")
            continue
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(orgs):
                return orgs[choice - 1]
        if raw in orgs:
            return raw
        print("Invalid selection. Try again.")


def _prompt_path(label: str) -> Path:
    while True:
        raw = input(label).strip().strip('"')
        if not raw:
            print("Input required.")
            continue
        value = Path(raw)
        if value.exists():
            return value
        print(f"Path does not exist: {value}")


def _prompt_with_default(label: str, default_value: str) -> str:
    raw = input(f"{label} [{default_value}]: ").strip()
    return raw or default_value


def _prompt_cross_date_lookahead() -> bool:
    print("\nQA/POS date scan mode:")
    print("  1. Include 30-day lookahead for cross-date payments/payouts [default]")
    print("  2. Only scan folders within the selected date range")
    while True:
        raw = input("Select [1]: ").strip() or "1"
        if raw == "1":
            return True
        if raw == "2":
            return False
        print("Enter 1 or 2.")


def _prompt_legacy_qa_side() -> tuple[str | None, Path | None]:
    """Ask which side uses QA/POS-computed data.

    Kept for compatibility with older call sites.
    """
    default_pos_dir = REPO_ROOT / "pos_data"
    print("\nUse QA (POS computed) data?")
    print("  1. No  — CenTech vs Client (normal)")
    print("  2. Right side — CenTech vs QA")
    print("  3. Left side  — QA vs Client")
    while True:
        raw = input("Select [1]: ").strip() or "1"
        if raw == "1":
            return None, None
        if raw in {"2", "3"}:
            side = "right" if raw == "2" else "left"
            while True:
                raw_dir = (
                    input(f"POS data directory [{default_pos_dir}]: ")
                    .strip()
                    .strip('"')
                )
                candidate = Path(raw_dir) if raw_dir else default_pos_dir
                # Try as-is, then relative to repo root
                if candidate.is_dir():
                    return side, candidate
                from_root = REPO_ROOT / candidate
                if from_root.is_dir():
                    return side, from_root
                print(f"Directory not found: {candidate}")
        print("Enter 1, 2, or 3.")


def _prompt_comparison_mode() -> tuple[str | None, Path | None, str]:
    """Ask for comparison mode in interactive runs."""
    default_pos_dir = REPO_ROOT / "pos_data"
    print("\nComparison mode:")
    print("  1. CenTech vs Client")
    print("  2. CenTech vs Flexe")
    print("  3. CenTech vs QA")
    print("  4. QA vs Client")
    print("  5. QA vs Flexe")

    while True:
        raw = input("Select [1]: ").strip() or "1"
        if raw == "1":
            return None, None, "client"
        if raw == "2":
            return None, None, "flexe"
        if raw in {"3", "4", "5"}:
            side = "right" if raw == "3" else "left"
            source_kind = "flexe" if raw == "5" else "client"
            while True:
                raw_dir = input(f"POS data directory [{default_pos_dir}]: ").strip().strip('"')
                candidate = Path(raw_dir) if raw_dir else default_pos_dir
                if candidate.is_dir():
                    return side, candidate, source_kind
                from_root = REPO_ROOT / candidate
                if from_root.is_dir():
                    return side, from_root, source_kind
                print(f"Directory not found: {candidate}")
        print("Enter 1, 2, 3, 4, or 5.")


def _find_root_export(prefix: str) -> Path | None:
    candidates = [
        REPO_ROOT / f"{prefix}.csv",
        REPO_ROOT / f"{prefix}.xlsx",
        REPO_ROOT / f"{prefix}.xls",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _find_run_input_export(run_input_dir: Path, prefix: str) -> Path | None:
    """Rerun: use files already archived under this run's input/ folder."""
    if not run_input_dir.is_dir():
        return None
    candidates = [
        run_input_dir / f"{prefix}.csv",
        run_input_dir / f"{prefix}.xlsx",
        run_input_dir / f"{prefix}.xls",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _source_root_prefix(source_kind: str) -> str:
    return "flexe_export" if source_kind == "flexe" else "client_export"


def _resolve_input_path(
    explicit_path: Path | None,
    *,
    root_prefix: str,
    run_input_dir: Path | None = None,
) -> Path:
    if explicit_path is not None:
        return explicit_path

    if run_input_dir is not None:
        run_hit = _find_run_input_export(run_input_dir, root_prefix)
        if run_hit is not None:
            print(
                f"[input] Using {run_hit.name} from run input (rerun): {run_input_dir}"
            )
            return run_hit

    found = _find_root_export(root_prefix)
    while found is None:
        print(
            f"[input] No {root_prefix}.csv/.xlsx/.xls in run input or repo root: {REPO_ROOT}"
        )
        input(f"Drop {root_prefix} in repo root or run input, then press Enter...")
        run_hit = (
            _find_run_input_export(run_input_dir, root_prefix)
            if run_input_dir
            else None
        )
        if run_hit is not None:
            print(f"[input] Using {run_hit.name} from run input: {run_input_dir}")
            return run_hit
        found = _find_root_export(root_prefix)
    print(f"[input] Using {found.name} from repo root")
    return found


def _ensure_run_dirs(run_dir: Path) -> None:
    (run_dir / "input").mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(parents=True, exist_ok=True)


def _archive_inputs_to_run(
    centech_path: Path, source_path: Path, input_dir: Path, *, source_kind: str = "client"
) -> None:
    """Move exports into this run's input/ folder (same idea as payroll moving Timesheet*.csv)."""
    input_dir.mkdir(parents=True, exist_ok=True)
    try:
        input_resolved = input_dir.resolve()
    except OSError:
        input_resolved = input_dir

    def move_one(src: Path, base_name: str) -> None:
        if not src.exists():
            return
        try:
            src_resolved = src.resolve()
        except OSError:
            return
        if src_resolved.parent == input_resolved:
            return
        dest = input_dir / f"{base_name}{src.suffix.lower()}"
        if dest.exists() and dest.resolve() != src_resolved:
            dest.unlink()
        shutil.move(str(src), str(dest))
        print(f"[input] Moved {src.name} -> {dest}")

    move_one(centech_path, "centech_export")
    move_one(source_path, _source_root_prefix(source_kind))


def _archive_centech_to_run(centech_path: Path, input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    try:
        input_resolved = input_dir.resolve()
        src_resolved = centech_path.resolve()
    except OSError:
        return
    if src_resolved.parent == input_resolved:
        return
    dest = input_dir / f"centech_export{centech_path.suffix.lower()}"
    if dest.exists() and dest.resolve() != src_resolved:
        dest.unlink()
    shutil.move(str(centech_path), str(dest))
    print(f"[input] Moved {centech_path.name} -> {dest}")


def _archive_source_to_run(source_path: Path, input_dir: Path, *, source_kind: str = "client") -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    try:
        input_resolved = input_dir.resolve()
        src_resolved = source_path.resolve()
    except OSError:
        return
    if src_resolved.parent == input_resolved:
        return
    dest = input_dir / f"{_source_root_prefix(source_kind)}{source_path.suffix.lower()}"
    if dest.exists() and dest.resolve() != src_resolved:
        dest.unlink()
    shutil.move(str(source_path), str(dest))
    print(f"[input] Moved {source_path.name} -> {dest}")


def _resolve_run_mode(
    *, centech_only: bool, pos_data_dir: Path | None, qa_on_left: bool, source_kind: str
) -> str:
    if centech_only:
        return "centech_only"
    if pos_data_dir is not None and qa_on_left:
        if source_kind == "flexe":
            return "qa_vs_flexe"
        return "qa_vs_client"
    if pos_data_dir is not None:
        return "centech_vs_qa"
    if source_kind == "flexe":
        return "centech_vs_flexe"
    return "centech_vs_client"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Financial sales export comparison pipeline."
    )
    parser.add_argument("--start", type=str, help="Start date (e.g. 'Mar 9 2026')")
    parser.add_argument("--end", type=str, help="End date (e.g. 'Mar 22 2026')")
    parser.add_argument(
        "--org", type=str, help="Organization key matching rules/<org>.yaml"
    )
    parser.add_argument(
        "--source-label",
        type=str,
        default=None,
        help="Header label for source side (D/E columns)",
    )
    parser.add_argument(
        "--centech-csv", type=str, default=None, help="Path to CenTech export CSV"
    )
    parser.add_argument(
        "--source-csv", type=str, default=None, help="Path to compared source CSV"
    )
    parser.add_argument(
        "--flexe-source",
        action="store_true",
        help=(
            "Treat --source-csv as a Flexe scrape export. Outputs use Flexe naming "
            "and the source is archived as flexe_export.*"
        ),
    )
    parser.add_argument(
        "--template",
        type=str,
        default=str(DEFAULT_TEMPLATE_PATH),
        help="Sales template xlsx path",
    )
    parser.add_argument(
        "--rules-dir", type=str, default=str(DEFAULT_RULES_DIR), help="Rules directory"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_RUNS_ROOT),
        help="Output directory root",
    )
    parser.add_argument(
        "--skip-data",
        action="store_true",
        help="Build workbook structure only; skip CSV comparison",
    )
    parser.add_argument(
        "--centech-only",
        action="store_true",
        help="Fill CenTech data only; no client file required",
    )
    parser.add_argument(
        "--pos-data-dir",
        type=str,
        default=None,
        help="Path to pos_data/ root; generates pos_computed.csv (QA vs CenTech by default)",
    )
    parser.add_argument(
        "--pos-source-date",
        type=str,
        default=None,
        help=(
            "Read every selected business day from this POS folder date when "
            "generating QA/POS data."
        ),
    )
    parser.add_argument(
        "--pos-source-date-from",
        type=str,
        default=None,
        help="First business date read from --pos-source-date.",
    )
    parser.add_argument(
        "--pos-source-date-through",
        type=str,
        default=None,
        help="Last business date read from --pos-source-date.",
    )
    parser.add_argument(
        "--qa-left",
        action="store_true",
        help="Put QA on left side (QA vs source) instead of right",
    )
    scan_group = parser.add_mutually_exclusive_group()
    scan_group.add_argument(
        "--strict-date-range",
        action="store_true",
        default=None,
        help=(
            "For diagnostic QA/POS verification only, scan folders within --start/--end; "
            "this disables payment-date lookahead and may not match Client exports."
        ),
    )
    scan_group.add_argument(
        "--include-cross-date-lookahead",
        action="store_true",
        default=None,
        help="For QA/POS verification, include the default 30-day lookahead after --end",
    )
    return parser


def _resolve_config(args: argparse.Namespace) -> RunConfig:
    rules_dir = Path(args.rules_dir)
    template_path = Path(args.template)
    output_dir = Path(args.output_dir)

    start_date = (
        parse_date_flexible(args.start)
        if args.start
        else _prompt_date("Start date (e.g. 'Mar 9 2026'): ")
    )
    end_date = (
        parse_date_flexible(args.end)
        if args.end
        else _prompt_date("End date (e.g. 'Mar 22 2026'): ")
    )
    if start_date > end_date:
        raise SystemExit("Start date must be <= end date.")

    centech_only = bool(args.centech_only)
    pos_data_dir = Path(args.pos_data_dir) if args.pos_data_dir else None
    pos_source_date = parse_date_flexible(args.pos_source_date) if args.pos_source_date else None
    pos_source_date_from = (
        parse_date_flexible(args.pos_source_date_from)
        if args.pos_source_date_from
        else None
    )
    pos_source_date_through = (
        parse_date_flexible(args.pos_source_date_through)
        if args.pos_source_date_through
        else None
    )
    if (pos_source_date_from or pos_source_date_through) and pos_source_date is None:
        raise SystemExit(
            "--pos-source-date-from/through require --pos-source-date."
        )
    qa_on_left = bool(getattr(args, "qa_left", False))
    source_kind = "flexe" if bool(getattr(args, "flexe_source", False)) else "client"
    if source_kind == "flexe" and pos_data_dir is not None and not qa_on_left:
        raise SystemExit("--flexe-source with --pos-data-dir requires --qa-left (QA vs Flexe).")

    org_key = args.org if args.org else _prompt_org(rules_dir)
    org_rule = load_org_rule(org_key, rules_dir)
    default_client_label = org_rule.client_header_label or org_rule.org_display_name

    # Interactive comparison-mode prompt when mode is not specified by args.
    if (
        not args.skip_data
        and not centech_only
        and pos_data_dir is None
        and not args.centech_csv
        and not args.flexe_source
    ):
        qa_side, prompted_pos_dir, prompted_source_kind = _prompt_comparison_mode()
        source_kind = prompted_source_kind
        if qa_side == "right":
            pos_data_dir = prompted_pos_dir
        elif qa_side == "left":
            pos_data_dir = prompted_pos_dir
            qa_on_left = True

    include_cross_date_lookahead = True
    if args.strict_date_range is True:
        include_cross_date_lookahead = False
    elif args.include_cross_date_lookahead is True:
        include_cross_date_lookahead = True
    elif not args.skip_data and pos_data_dir is not None:
        include_cross_date_lookahead = _prompt_cross_date_lookahead()

    if centech_only:
        source_label = args.source_label or default_client_label
    elif source_kind == "flexe":
        source_label = args.source_label or "Flexe"
    elif pos_data_dir is not None and not qa_on_left:
        source_label = args.source_label or "QA"
    elif pos_data_dir is not None and qa_on_left:
        source_label = args.source_label or _prompt_with_default(
            "Right side label (D/E columns)",
            default_client_label,
        )
    else:
        source_label = args.source_label or _prompt_with_default(
            "Whose client export is this? (label for D/E columns)",
            default_client_label,
        )

    centech_csv = Path(args.centech_csv) if args.centech_csv else None
    source_csv = Path(args.source_csv) if args.source_csv else None

    run_mode = _resolve_run_mode(
        centech_only=centech_only,
        pos_data_dir=pos_data_dir,
        qa_on_left=qa_on_left,
        source_kind=source_kind,
    )

    if not args.skip_data:
        period_key = build_period_key(start_date, end_date)
        run_input_dir = output_dir / period_key / org_key / run_mode / "input"

        if not qa_on_left:
            # CenTech export always on left unless QA takes that slot
            centech_csv = _resolve_input_path(
                centech_csv,
                root_prefix="centech_export",
                run_input_dir=run_input_dir,
            )

        if not centech_only and (pos_data_dir is None or qa_on_left):
            # Need client export on right when: no QA, or QA is on left
            source_csv = _resolve_input_path(
                source_csv,
                root_prefix=_source_root_prefix(source_kind),
                run_input_dir=run_input_dir,
            )

    return RunConfig(
        start_date=start_date,
        end_date=end_date,
        org_key=org_key,
        source_label=source_label,
        template_path=template_path,
        rules_dir=rules_dir,
        output_dir=output_dir,
        run_mode=run_mode,
        centech_csv=centech_csv,
        source_csv=source_csv,
        source_kind=source_kind,
        skip_data=args.skip_data,
        centech_only=centech_only,
        pos_data_dir=pos_data_dir,
        qa_on_left=qa_on_left,
        centech_label="QA" if qa_on_left else "CenTech",
        include_cross_date_lookahead=include_cross_date_lookahead,
        pos_source_date=pos_source_date,
        pos_source_date_from=pos_source_date_from,
        pos_source_date_through=pos_source_date_through,
    )


def main() -> None:
    args = _build_parser().parse_args()
    config = _resolve_config(args)
    org_rule = load_org_rule(config.org_key, config.rules_dir)

    period_key = build_period_key(config.start_date, config.end_date)
    run_dir = config.output_dir / period_key / config.org_key / config.run_mode
    _MODE_LABEL = {
        "centech_vs_client": "CenTech_vs_Client",
        "centech_vs_flexe":  "CenTech_vs_Flexe",
        "centech_vs_qa":     "CenTech_vs_QA",
        "qa_vs_client":      "QA_vs_Client",
        "qa_vs_flexe":       "QA_vs_Flexe",
        "centech_only":      "CenTech_only",
    }
    _mode_label = _MODE_LABEL.get(config.run_mode, config.run_mode)
    output_workbook = run_dir / "output" / f"Sales_{_mode_label}_{period_key}.xlsx"

    pos_computed_csv = run_dir / "output" / "pos_computed.csv"

    print("\n=== Financial Sales Export Comparison ===")
    print(f"Period       : {period_key}")
    print(f"Organization : {org_rule.org_display_name} ({config.org_key})")
    print(f"Stores       : {', '.join(org_rule.stores)}")
    print(f"Template     : {config.template_path}")
    print(f"Run mode     : {config.run_mode}")
    print(f"Output       : {output_workbook}")
    if config.skip_data:
        print("Data mode    : skipped (--skip-data)")
    elif config.centech_only:
        print("Data mode    : CenTech only (no client comparison)")
        print(f"CenTech CSV  : {config.centech_csv}")
    elif config.pos_data_dir is not None and config.qa_on_left:
        print(f"Data mode    : QA vs {config.source_label} (QA on left)")
        print(f"POS data dir : {config.pos_data_dir}")
        if config.pos_source_date is not None:
            print(f"POS source   : {config.pos_source_date.isoformat()}")
            if config.pos_source_date_from or config.pos_source_date_through:
                print(
                    "POS source window: "
                    f"{config.pos_source_date_from or config.start_date} through "
                    f"{config.pos_source_date_through or config.end_date}"
                )
        print(
            "QA scan mode : "
            + ("date range + 30-day lookahead" if config.include_cross_date_lookahead else "selected date range only")
        )
        print(f"QA CSV out   : {pos_computed_csv}")
        print(f"{config.source_label} CSV   : {config.source_csv}")
    elif config.pos_data_dir is not None:
        print("Data mode    : CenTech vs QA (QA on right)")
        print(f"CenTech CSV  : {config.centech_csv}")
        print(f"POS data dir : {config.pos_data_dir}")
        if config.pos_source_date is not None:
            print(f"POS source   : {config.pos_source_date.isoformat()}")
        print(
            "QA scan mode : "
            + ("date range + 30-day lookahead" if config.include_cross_date_lookahead else "selected date range only")
        )
        print(f"QA CSV out   : {pos_computed_csv}")
    else:
        print(f"CenTech CSV  : {config.centech_csv}")
        print(f"{config.source_label} CSV   : {config.source_csv}")

    proceed = input("\nContinue? [Y/n]: ").strip().lower()
    if proceed in {"n", "no"}:
        raise SystemExit("Cancelled.")

    _ensure_run_dirs(run_dir)

    stage_total = 1
    if not config.skip_data and (config.centech_csv or config.pos_data_dir):
        if config.pos_data_dir is not None:
            stage_total += 1
        stage_total += 1
        if not config.centech_only:
            stage_total += 1
        stage_total += 1
        stage_total += 1

    with tqdm(total=stage_total, desc="[pipeline] Sales comparison", unit="stage") as stage_bar:
        stage_bar.set_postfix_str("template")
        build_template_workbook(
            template_path=config.template_path,
            output_path=output_workbook,
            start_date=config.start_date,
            end_date=config.end_date,
            stores=org_rule.stores,
            source_label=config.source_label,
            sheet_name_format=org_rule.sheet_date_format,
            layout=DEFAULT_LAYOUT,
            centech_only=config.centech_only,
            centech_label=config.centech_label,
        )
        stage_bar.update(1)
        tqdm.write(f"[template] Workbook skeleton created -> {output_workbook}")

        if not config.skip_data and (config.centech_csv or config.pos_data_dir):
            centech_path = config.centech_csv
            source_csv = config.source_csv
            client_side_config = None
            centech_side_config = None
            if config.source_kind == "flexe":
                client_side_config = org_rule.qa

            if config.pos_data_dir is not None:
                _ensure_run_dirs(run_dir)
                if pos_computed_csv.exists():
                    answer = input(f"QA data already exists at {pos_computed_csv}\nRegenerate? [y/N]: ").strip().lower()
                    regenerate = answer in {"y", "yes"}
                else:
                    regenerate = True
                stage_bar.set_postfix_str("verifier")
                if regenerate:
                    qa_rows = run_verifier(
                        VerifierConfig(
                            pos_data_dir=config.pos_data_dir,
                            stores=org_rule.stores,
                            start_date=config.start_date,
                            end_date=config.end_date,
                            output_csv_path=pos_computed_csv,
                            include_cross_date_lookahead=config.include_cross_date_lookahead,
                            pos_source_date=config.pos_source_date,
                            pos_source_date_from=config.pos_source_date_from,
                            pos_source_date_through=config.pos_source_date_through,
                        )
                    )
                    tqdm.write(f"[verifier] QA CSV written ({qa_rows} rows) -> {pos_computed_csv}")
                else:
                    tqdm.write(f"[verifier] Using existing QA CSV -> {pos_computed_csv}")
                stage_bar.update(1)

                if config.qa_on_left:
                    # QA fills centech (left) slot; use qa config so date auto-detection
                    # handles pos_computed.csv (MM/DD/YYYY) without the centech date_parse_format
                    centech_path = pos_computed_csv
                    centech_side_config = org_rule.qa
                    # source_csv = client_export (already resolved in _resolve_config)
                else:
                    # QA fills source (right) slot; use qa config to avoid online_credit_card handler
                    source_csv = pos_computed_csv
                    client_side_config = org_rule.qa

            if centech_path is None:
                raise SystemExit("Missing CenTech-side input for generator run.")

            stage_bar.set_postfix_str("generator")
            generated = run_generator(
                WorkbookFillConfig(
                    workbook_path=output_workbook,
                    org_rule=org_rule,
                    centech_path=centech_path,
                    client_path=source_csv,
                    start_date=config.start_date,
                    end_date=config.end_date,
                    client_side_config=client_side_config,
                    centech_side_config=centech_side_config,
                )
            )
            stage_bar.update(1)
            tqdm.write(
                f"[generator] Rows written (centech={generated.centech_rows_written}, client={generated.client_rows_written})"
            )

            if not config.centech_only:
                ignored_categories = org_rule.ignored_categories | generated.ignored_categories
                if config.run_mode == "centech_vs_qa":
                    ignored_categories -= {
                        "Online Credit Card Tips",
                        "Online Gift Card Tips",
                    }
                if generated.ignored_categories:
                    tqdm.write(
                        "[heatmap] Ignoring client combined OLO categories: "
                        + ", ".join(sorted(generated.ignored_categories))
                    )
                stage_bar.set_postfix_str("heatmap")
                run_heatmap(
                    HeatmapConfig(
                        workbook_path=output_workbook,
                        stores=org_rule.stores,
                        category_rows=org_rule.category_rows,
                        tolerance=org_rule.mismatch_tolerance,
                        layout=DEFAULT_LAYOUT,
                        ignored_categories=ignored_categories,
                        source_label=config.source_label,
                        centech_label=config.centech_label,
                    )
                )
                stage_bar.update(1)
                tqdm.write("[heatmap] Mismatch heatmap applied.")

            if centech_path:
                stage_bar.set_postfix_str("diagnostics")
                run_diagnostics(
                    DiagnosticsConfig(
                        workbook_path=output_workbook,
                        centech_path=centech_path,
                        org_rule=org_rule,
                        start_date=config.start_date,
                        end_date=config.end_date,
                        tolerance=org_rule.mismatch_tolerance,
                    )
                )
                stage_bar.update(1)
                tqdm.write("[diagnostics] Diagnostics tab written.")

            stage_bar.set_postfix_str("archive")
            real_centech = config.centech_csv  # original export, not QA-generated
            real_source = source_csv if source_csv != pos_computed_csv else None
            if real_centech and real_source:
                _archive_inputs_to_run(
                    real_centech,
                    real_source,
                    run_dir / "input",
                    source_kind=config.source_kind,
                )
            elif real_centech:
                _archive_centech_to_run(real_centech, run_dir / "input")
            elif real_source:
                _archive_source_to_run(real_source, run_dir / "input", source_kind=config.source_kind)
            stage_bar.update(1)

    print("\n=== Done ===")
    print(f"Workbook: {output_workbook}")
    if not config.skip_data:
        print(f"Run folder : {run_dir}")
        print(f"Inputs     : {run_dir / 'input'}")
        print(f"Outputs    : {run_dir / 'output'}")


if __name__ == "__main__":
    main()
