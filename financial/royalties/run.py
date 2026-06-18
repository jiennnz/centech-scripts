from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from dateutil import parser as date_parser

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from financial.royalties.stages.comparison import (  # noqa: E402
    RoyaltyComparisonConfig,
    run as run_comparison,
)
from financial.royalties.stages.verifier import (  # noqa: E402
    RoyaltyVerifierConfig,
    run as run_verifier,
)
from financial.sales_export_comparison.rules import (  # noqa: E402
    available_orgs,
    load_org_rule,
)


DEFAULT_RULES_DIR = REPO_ROOT / "financial" / "sales_export_comparison" / "rules"
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "Royalties_Template.xlsx"
DEFAULT_RUNS_ROOT = REPO_ROOT / "financial" / "royalties" / "runs"
DEFAULT_CENTECH_EXPORT = REPO_ROOT / "centech_royalties.xlsx"
DEFAULT_CLIENT_EXPORT = REPO_ROOT / "client_royalties.csv"
DEFAULT_POS_DATA_DIR = REPO_ROOT / "pos_data"
CENTECH_RANGE_PREFIX = "centech_royalties"
CLIENT_RANGE_PREFIX = "client_royalties"
CENTECH_RANGE_EXTENSIONS = (".xlsx", ".xls", ".csv")
CLIENT_RANGE_EXTENSIONS = (".csv", ".xlsx", ".xls")


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
    centech_path: tuple[Path, ...] | None
    client_path: tuple[Path, ...] | None
    pos_data_dir: Path | None = None
    qa_on_left: bool = False
    daily_inputs: bool = False
    combined_inputs: bool = False
    daily_input_dir: Path | None = None
    centech_label: str = "CenTech"
    include_cross_date_lookahead: bool = True
    yes: bool = False


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
        raw = input("Select org (name or number) [century]: ").strip() or "century"
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(orgs):
                return orgs[choice - 1]
        if raw in orgs:
            return raw
        print("Invalid selection. Try again.")


def _resolve_existing_path(raw: str | None, default_path: Path, label: str) -> Path:
    path = Path(raw).expanduser() if raw else default_path
    if path.exists():
        return path
    raise SystemExit(f"{label} not found: {path}")


def _find_named_export(directory: Path, prefix: str, extensions: tuple[str, ...]) -> Path | None:
    for suffix in extensions:
        candidate = directory / f"{prefix}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _find_export_by_names(directory: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _centech_report_name(start_date: date, end_date: date) -> str:
    return f"royalties_report_{start_date.isoformat()}_to_{end_date.isoformat()}.xlsx"


def _centech_range_names(start_date: date, end_date: date) -> tuple[str, ...]:
    return (
        _centech_report_name(start_date, end_date),
        "centech_royalties.xlsx",
        "centech_royalties.xls",
        "centech_royalties.csv",
    )


def _resolve_range_input_path(
    explicit_path: str | None,
    *,
    prefix: str,
    extensions: tuple[str, ...],
    run_input_dir: Path,
    label: str,
    candidate_names: tuple[str, ...] | None = None,
    prompt_for_existing_run_client: bool = False,
    yes: bool = False,
) -> Path:
    if explicit_path:
        return _resolve_existing_path(explicit_path, Path(explicit_path), label)

    def find_export(directory: Path) -> Path | None:
        if candidate_names is not None:
            return _find_export_by_names(directory, candidate_names)
        return _find_named_export(directory, prefix, extensions)

    expected = (
        "/".join(candidate_names)
        if candidate_names is not None
        else "/".join(f"{prefix}{suffix}" for suffix in extensions)
    )

    run_hit = find_export(run_input_dir)
    root_hit = find_export(REPO_ROOT)

    if prompt_for_existing_run_client and run_hit is not None and not yes:
        print(f"\nExisting {label} found in this run input folder:")
        print(f"  {run_hit}")
        answer = input(
            f"Use existing {label} from this run? [Y/n] "
            f"(choose n to use {prefix} from repo root): "
        ).strip().lower()
        if answer not in {"n", "no"}:
            return run_hit
        if root_hit is not None:
            return root_hit
        while root_hit is None:
            input(f"Put a new {prefix} file in repo root, then press Enter...")
            root_hit = find_export(REPO_ROOT)
        return root_hit

    if root_hit is not None:
        print(f"[input] Using {root_hit.name} from repo root")
        return root_hit
    if run_hit is not None:
        print(f"[input] Using {run_hit.name} from run input: {run_input_dir}")
        return run_hit

    if yes:
        raise SystemExit(f"{label} not found. Expected {expected} in repo root or run input.")

    while True:
        input(f"[input] Add {expected} to repo root or run input, then press Enter...")
        root_hit = find_export(REPO_ROOT)
        if root_hit is not None:
            print(f"[input] Using {root_hit.name} from repo root")
            return root_hit
        run_hit = find_export(run_input_dir)
        if run_hit is not None:
            print(f"[input] Using {run_hit.name} from run input: {run_input_dir}")
            return run_hit


def _as_single_path_tuple(path: Path | None) -> tuple[Path, ...] | None:
    return (path,) if path is not None else None


def _resolve_input_dir(raw: str | None) -> Path:
    candidate = Path(raw).expanduser() if raw else REPO_ROOT
    if candidate.is_dir():
        return candidate
    from_root = REPO_ROOT / candidate
    if from_root.is_dir():
        return from_root
    raise SystemExit(f"Daily input directory not found: {candidate}")


def _collect_numbered_files(input_dir: Path, *, prefix: str, suffix: str) -> dict[int, Path]:
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+){re.escape(suffix)}$", re.IGNORECASE)
    matches: dict[int, Path] = {}
    duplicates: dict[int, list[Path]] = {}
    for path in input_dir.iterdir():
        if not path.is_file():
            continue
        match = pattern.match(path.name)
        if not match:
            continue
        number = int(match.group(1))
        if number in matches:
            duplicates.setdefault(number, [matches[number]]).append(path)
            continue
        matches[number] = path
    if duplicates:
        details = ", ".join(
            f"{number}: {', '.join(p.name for p in paths)}"
            for number, paths in sorted(duplicates.items())
        )
        raise SystemExit(f"Duplicate daily {prefix} files found in {input_dir}: {details}")
    return matches


def _format_number_set(values: set[int]) -> str:
    if not values:
        return "none"
    return ", ".join(str(value) for value in sorted(values))


def _resolve_daily_input_paths(
    *,
    input_dir: Path,
    start_date: date,
    end_date: date,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    expected_count = (end_date - start_date).days + 1
    expected_numbers = set(range(1, expected_count + 1))
    expected_dates = tuple(start_date + timedelta(days=idx) for idx in range(expected_count))
    centech_by_number = _collect_numbered_files(
        input_dir,
        prefix="centech_royalties",
        suffix=".xlsx",
    )
    client_by_number = _collect_numbered_files(
        input_dir,
        prefix="client_royalties",
        suffix=".csv",
    )

    def validate(side: str, found: dict[int, Path]) -> None:
        found_numbers = set(found)
        missing = expected_numbers - found_numbers
        extra = found_numbers - expected_numbers
        if missing or extra:
            raise SystemExit(
                f"Expected {expected_count} {side} daily royalty files numbered "
                f"1-{expected_count} in {input_dir}. "
                f"Missing: {_format_number_set(missing)}. Extra: {_format_number_set(extra)}."
            )

    centech_paths: tuple[Path, ...] | None = None
    daily_report_paths = tuple(
        input_dir / _centech_report_name(day, day)
        for day in expected_dates
    )
    if all(path.exists() for path in daily_report_paths):
        centech_paths = daily_report_paths
    else:
        validate("CenTech", centech_by_number)
        centech_paths = tuple(centech_by_number[number] for number in sorted(expected_numbers))

    validate("client", client_by_number)

    return (
        centech_paths,
        tuple(client_by_number[number] for number in sorted(expected_numbers)),
    )


def _prompt_pos_data_dir() -> Path:
    while True:
        raw = input(f"POS data directory [{DEFAULT_POS_DATA_DIR}]: ").strip().strip('"')
        candidate = Path(raw).expanduser() if raw else DEFAULT_POS_DATA_DIR
        if candidate.is_dir():
            return candidate
        from_root = REPO_ROOT / candidate
        if from_root.is_dir():
            return from_root
        print(f"Directory not found: {candidate}")


def _prompt_comparison_mode() -> tuple[Path | None, bool, bool, bool]:
    """Return (pos_data_dir, qa_on_left, daily_inputs, combined_inputs)."""
    print("\nRoyalties comparison mode:")
    print("  1. CenTech vs Client (date range)")
    print("  2. CenTech vs Client (daily files)")
    print("  3. CenTech vs Client (date range + daily files)")
    print("  4. CenTech vs QA")
    print("  5. QA vs Client")
    while True:
        raw = input("Select [1]: ").strip() or "1"
        if raw == "1":
            return None, False, False, False
        if raw == "2":
            return None, False, True, False
        if raw == "3":
            return None, False, False, True
        if raw == "4":
            return _prompt_pos_data_dir(), False, False, False
        if raw == "5":
            return _prompt_pos_data_dir(), True, False, False
        print("Enter 1, 2, 3, 4, or 5.")


def _prompt_cross_date_lookahead() -> bool:
    print("\nQA/POS royalty scan mode:")
    print("  1. Include royalty lookback/lookahead scan window [default]")
    print("  2. Only scan folders within the selected date range")
    while True:
        raw = input("Select [1]: ").strip() or "1"
        if raw == "1":
            return True
        if raw == "2":
            return False
        print("Enter 1 or 2.")


def _archive_input_to_run(path: Path | None, input_dir: Path, base_name: str | None) -> Path | None:
    if path is None:
        return None
    input_dir.mkdir(parents=True, exist_ok=True)
    dest = input_dir / (path.name if base_name is None else f"{base_name}{path.suffix.lower()}")
    if _same_path(path, dest):
        return dest
    if dest.exists():
        dest.unlink()
    shutil.move(str(path), str(dest))
    print(f"[input] Moved {path.name} -> {dest}")
    return dest


def _archive_daily_inputs_to_run(paths: tuple[Path, ...] | None, input_dir: Path) -> tuple[Path, ...] | None:
    if not paths:
        return None
    input_dir.mkdir(parents=True, exist_ok=True)
    archived: list[Path] = []
    for path in paths:
        dest = input_dir / path.name
        if _same_path(path, dest):
            archived.append(dest)
            continue
        if dest.exists():
            dest.unlink()
        shutil.move(str(path), str(dest))
        print(f"[input] Moved {path.name} -> {dest}")
        archived.append(dest)
    return tuple(archived)


def _first_path(paths: tuple[Path, ...] | None) -> Path | None:
    return paths[0] if paths else None


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _resolve_run_mode(
    *,
    pos_data_dir: Path | None,
    qa_on_left: bool,
    daily_inputs: bool,
    combined_inputs: bool,
) -> str:
    if combined_inputs:
        return "centech_vs_client_combined"
    if daily_inputs:
        return "centech_vs_client_daily"
    if pos_data_dir is None:
        return "centech_vs_client"
    if qa_on_left:
        return "qa_vs_client"
    return "centech_vs_qa"


def _file_label(raw: str) -> str:
    clean = "".join(ch if ch.isalnum() else "_" for ch in raw.strip())
    clean = "_".join(part for part in clean.split("_") if part)
    return clean or "Source"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the royalties financial comparison workbook.",
    )
    parser.add_argument("--start", type=str, default=None, help="Start date (e.g. 2026-05-04)")
    parser.add_argument("--end", type=str, default=None, help="End date (e.g. 2026-05-10)")
    parser.add_argument("--org", type=str, default=None, help="Organization rule key (default: prompt/century)")
    parser.add_argument("--rules-dir", type=str, default=str(DEFAULT_RULES_DIR))
    parser.add_argument("--template", type=str, default=str(DEFAULT_TEMPLATE_PATH))
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument(
        "--centech",
        type=str,
        default=None,
        help=(
            "CenTech royalties export path "
            "(default: royalties_report_<start>_to_<end>.xlsx)"
        ),
    )
    parser.add_argument("--client", type=str, default=None, help="Client royalties export path (default: client_royalties.*)")
    parser.add_argument(
        "--daily-inputs",
        action="store_true",
        help=(
            "Compare numbered daily files instead of one range export. "
            "Expected CenTech names: royalties_report_<date>_to_<date>.xlsx; "
            "client names: client_royalties_<n>.csv"
        ),
    )
    parser.add_argument(
        "--combined-inputs",
        action="store_true",
        help=(
            "Compare both the date-range exports and daily exports in one workbook."
        ),
    )
    parser.add_argument(
        "--daily-input-dir",
        type=str,
        default=None,
        help="Directory containing daily royalty files (default: repo root)",
    )
    parser.add_argument(
        "--pos-data-dir",
        type=str,
        default=None,
        help="Path to pos_data/ root; generates a POS-computed QA royalties export",
    )
    parser.add_argument(
        "--qa-left",
        action="store_true",
        help="Put QA on the left side (QA vs Client) instead of the right side",
    )
    scan_group = parser.add_mutually_exclusive_group()
    scan_group.add_argument(
        "--strict-date-range",
        action="store_true",
        default=None,
        help="For QA verification, scan only folders within --start/--end",
    )
    scan_group.add_argument(
        "--include-cross-date-lookahead",
        action="store_true",
        default=None,
        help="For QA verification, include the default royalty lookback/lookahead scan window",
    )
    parser.add_argument("--source-label", type=str, default=None, help="Client column label")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    return parser


def _resolve_config(args: argparse.Namespace) -> RunConfig:
    rules_dir = Path(args.rules_dir)
    org_key = args.org or _prompt_org(rules_dir)

    start_date = parse_date_flexible(args.start) if args.start else _prompt_date("Start date: ")
    end_date = parse_date_flexible(args.end) if args.end else _prompt_date("End date: ")
    if start_date > end_date:
        raise SystemExit("Start date must be <= end date.")

    org_rule = load_org_rule(org_key, rules_dir)
    daily_inputs = bool(args.daily_inputs)
    combined_inputs = bool(args.combined_inputs)
    pos_data_dir = Path(args.pos_data_dir) if args.pos_data_dir else None
    qa_on_left = bool(args.qa_left)
    if pos_data_dir is None and not args.centech and not args.client and not daily_inputs and not combined_inputs:
        pos_data_dir, qa_on_left, daily_inputs, combined_inputs = _prompt_comparison_mode()

    if daily_inputs and combined_inputs:
        raise SystemExit("--daily-inputs and --combined-inputs cannot be used together.")
    if args.daily_input_dir and not (daily_inputs or combined_inputs):
        raise SystemExit("--daily-input-dir requires --daily-inputs or --combined-inputs.")
    if daily_inputs and (args.centech or args.client):
        raise SystemExit("--daily-inputs cannot be combined with --centech or --client.")
    if (daily_inputs or combined_inputs) and (args.pos_data_dir or args.qa_left):
        raise SystemExit("Daily/combined input modes support CenTech vs Client files only.")
    if combined_inputs and start_date == end_date:
        raise SystemExit("--combined-inputs requires a multi-day date range.")

    if pos_data_dir is not None and not pos_data_dir.is_dir():
        raise SystemExit(f"POS data directory not found: {pos_data_dir}")
    if qa_on_left and pos_data_dir is None:
        raise SystemExit("--qa-left requires --pos-data-dir.")

    if pos_data_dir is not None and not qa_on_left:
        source_label = args.source_label or "QA"
    else:
        source_label = args.source_label or org_rule.client_header_label or "Client"

    include_cross_date_lookahead = True
    if args.strict_date_range is True:
        include_cross_date_lookahead = False
    elif args.include_cross_date_lookahead is True:
        include_cross_date_lookahead = True
    elif pos_data_dir is not None and not args.yes:
        include_cross_date_lookahead = _prompt_cross_date_lookahead()

    centech_path: tuple[Path, ...] | None = None
    client_path: tuple[Path, ...] | None = None
    daily_input_dir = None
    run_mode = _resolve_run_mode(
        pos_data_dir=pos_data_dir,
        qa_on_left=qa_on_left,
        daily_inputs=daily_inputs,
        combined_inputs=combined_inputs,
    )
    period_key = build_period_key(start_date, end_date)
    run_input_dir = Path(args.output_dir) / period_key / org_key / run_mode / "input"
    if daily_inputs:
        daily_input_dir = _resolve_input_dir(args.daily_input_dir)
        centech_path, client_path = _resolve_daily_input_paths(
            input_dir=daily_input_dir,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        if pos_data_dir is None or not qa_on_left:
            centech_path = _as_single_path_tuple(
                _resolve_range_input_path(
                    args.centech,
                    prefix=CENTECH_RANGE_PREFIX,
                    extensions=CENTECH_RANGE_EXTENSIONS,
                    run_input_dir=run_input_dir,
                    label="CenTech export",
                    candidate_names=_centech_range_names(start_date, end_date),
                    yes=bool(args.yes),
                )
            )
        if pos_data_dir is None or qa_on_left:
            client_path = _as_single_path_tuple(
                _resolve_range_input_path(
                    args.client,
                    prefix=CLIENT_RANGE_PREFIX,
                    extensions=CLIENT_RANGE_EXTENSIONS,
                    run_input_dir=run_input_dir,
                    label="client export",
                    prompt_for_existing_run_client=True,
                    yes=bool(args.yes),
                )
            )
        if combined_inputs:
            daily_input_dir = _resolve_input_dir(args.daily_input_dir)
            daily_centech_path, daily_client_path = _resolve_daily_input_paths(
                input_dir=daily_input_dir,
                start_date=start_date,
                end_date=end_date,
            )
            centech_path = (centech_path or ()) + daily_centech_path
            client_path = (client_path or ()) + daily_client_path

    return RunConfig(
        start_date=start_date,
        end_date=end_date,
        org_key=org_key,
        source_label=source_label,
        template_path=_resolve_existing_path(args.template, DEFAULT_TEMPLATE_PATH, "Template"),
        rules_dir=rules_dir,
        output_dir=Path(args.output_dir),
        run_mode=run_mode,
        centech_path=centech_path,
        client_path=client_path,
        pos_data_dir=pos_data_dir,
        qa_on_left=qa_on_left,
        daily_inputs=daily_inputs,
        combined_inputs=combined_inputs,
        daily_input_dir=daily_input_dir,
        centech_label="QA" if qa_on_left else "CenTech",
        include_cross_date_lookahead=include_cross_date_lookahead,
        yes=bool(args.yes),
    )


def main() -> None:
    args = _build_parser().parse_args()
    config = _resolve_config(args)
    org_rule = load_org_rule(config.org_key, config.rules_dir)
    period_key = build_period_key(config.start_date, config.end_date)
    run_dir = config.output_dir / period_key / config.org_key / config.run_mode
    left_label = _file_label(config.centech_label)
    right_label = _file_label(config.source_label)
    output_workbook = (
        run_dir
        / "output"
        / f"Royalties_{left_label}_vs_{right_label}_{period_key}.xlsx"
    )
    pos_computed_csv = run_dir / "output" / "pos_computed.csv"

    print("\n=== Financial Royalties Comparison ===")
    print(f"Period       : {period_key}")
    print(f"Organization : {org_rule.org_display_name} ({config.org_key})")
    print(f"Stores       : {len(org_rule.stores)}")
    print(f"Template     : {config.template_path}")
    print(f"Run mode     : {config.run_mode}")
    if config.pos_data_dir is not None and config.qa_on_left:
        print("Data mode    : QA vs Client (QA on left)")
        print(f"POS data dir : {config.pos_data_dir}")
        print(
            "QA scan mode : "
            + ("royalty lookback/lookahead" if config.include_cross_date_lookahead else "selected date range only")
        )
        print(f"QA CSV out   : {pos_computed_csv}")
        print(f"Client CSV   : {_first_path(config.client_path)}")
    elif config.pos_data_dir is not None:
        print("Data mode    : CenTech vs QA (QA on right)")
        print(f"CenTech XLSX : {_first_path(config.centech_path)}")
        print(f"POS data dir : {config.pos_data_dir}")
        print(
            "QA scan mode : "
            + ("royalty lookback/lookahead" if config.include_cross_date_lookahead else "selected date range only")
        )
        print(f"QA CSV out   : {pos_computed_csv}")
    elif config.daily_inputs:
        print("Data mode    : Daily CenTech vs Client files")
        print(f"Daily inputs : {config.daily_input_dir}")
        print(f"Daily pairs  : {len(config.centech_path or ())}")
    elif config.combined_inputs:
        print("Data mode    : Date range + daily CenTech vs Client files")
        print(f"Daily inputs : {config.daily_input_dir}")
        print(f"CenTech files: {len(config.centech_path or ())}")
        print(f"Client files : {len(config.client_path or ())}")
    else:
        print(f"CenTech XLSX : {_first_path(config.centech_path)}")
        print(f"Client CSV   : {_first_path(config.client_path)}")
    print(f"Output       : {output_workbook}")

    if not config.yes:
        proceed = input("\nContinue? [Y/n]: ").strip().lower()
        if proceed in {"n", "no"}:
            raise SystemExit("Cancelled.")

    (run_dir / "input").mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(parents=True, exist_ok=True)
    if config.daily_inputs or config.combined_inputs:
        centech_path = _archive_daily_inputs_to_run(config.centech_path, run_dir / "input")
        client_path = _archive_daily_inputs_to_run(config.client_path, run_dir / "input")
    else:
        centech_path = _as_single_path_tuple(_archive_input_to_run(
            _first_path(config.centech_path),
            run_dir / "input",
            None,
        ))
        client_path = _as_single_path_tuple(_archive_input_to_run(
            _first_path(config.client_path),
            run_dir / "input",
            CLIENT_RANGE_PREFIX,
        ))
    if config.pos_data_dir is not None:
        regenerate = True
        if pos_computed_csv.exists() and not config.yes:
            answer = input(f"QA data already exists at {pos_computed_csv}\nRegenerate? [y/N]: ").strip().lower()
            regenerate = answer in {"y", "yes"}
        if regenerate:
            qa_rows = run_verifier(
                RoyaltyVerifierConfig(
                    pos_data_dir=config.pos_data_dir,
                    stores=org_rule.stores,
                    start_date=config.start_date,
                    end_date=config.end_date,
                    output_csv_path=pos_computed_csv,
                    detail_csv_path=run_dir / "output" / "pos_computed_detail.csv",
                    summary_csv_path=run_dir / "output" / "pos_computed_summary.csv",
                    skipped_csv_path=run_dir / "output" / "pos_computed_skipped_store_days.csv",
                    include_cross_date_lookahead=config.include_cross_date_lookahead,
                )
            )
            print(f"[royalty verifier] QA CSV written ({qa_rows} rows) -> {pos_computed_csv}")
        else:
            print(f"[royalty verifier] Using existing QA CSV -> {pos_computed_csv}")

        if config.qa_on_left:
            centech_path = (pos_computed_csv,)
        else:
            client_path = (pos_computed_csv,)

    if centech_path is None:
        raise SystemExit("Missing left-side royalties input.")
    if client_path is None:
        raise SystemExit("Missing right-side royalties input.")

    try:
        result = run_comparison(
            RoyaltyComparisonConfig(
                template_path=config.template_path,
                output_path=output_workbook,
                centech_path=centech_path,
                client_path=client_path,
                stores=org_rule.stores,
                start_date=config.start_date,
                end_date=config.end_date,
                source_label=config.source_label,
                centech_label=config.centech_label,
                tolerance=0.0,
            )
        )
    except ValueError as exc:
        raise SystemExit(f"\nError: {exc}") from None

    print("\n=== Done ===")
    print(f"Workbook                : {result.output_path}")
    print(f"DateRange tabs          : {len(result.periods)}")
    print(f"Rows written (CenTech)  : {result.centech_rows_written}")
    print(f"Rows written (Client)   : {result.client_rows_written}")
    print(f"Account mapping diffs   : {result.account_mapping_differences}")
    print(f"Run folder              : {run_dir}")


if __name__ == "__main__":
    main()
