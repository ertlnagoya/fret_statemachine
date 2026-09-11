"""Command-line interface for FRET-to-pytransitions conversion."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    # Support ``python path/to/fret2transitions`` as well as ``python -m``.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from fret2transitions.converter import build_state_machine, load_fret_export
    from fret2transitions.errors import ConversionError
    from fret2transitions.generator import generate_module
else:
    from .converter import build_state_machine, load_fret_export
    from .errors import ConversionError
    from .generator import generate_module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fret2transitions",
        description="Generate a transitions.Machine module from exported FRETish FSM requirements.",
    )
    parser.add_argument("input", type=Path, help="FRET requirements JSON export")
    parser.add_argument("-o", "--output", type=Path, required=True, help="generated .py file")
    parser.add_argument("--component", help="component to convert when JSON contains several")
    parser.add_argument("--state-variable", help="state variable when it cannot be inferred")
    parser.add_argument("--initial", help="override a missing initial-state requirement")
    parser.add_argument("--class-name", help="generated Python class name")
    parser.add_argument(
        "--guard-semantics",
        choices=("rising", "level"),
        default="rising",
        help="Upon edge semantics (default) or conventional level guards",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="reject unsupported requirements and missing retention requirements",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        exported = load_fret_export(args.input)
        spec = build_state_machine(
            exported.requirements,
            exported.variables,
            component=args.component,
            state_variable=args.state_variable,
            initial_state=args.initial,
            strict=args.strict,
        )
        source = generate_module(
            spec,
            class_name=args.class_name,
            guard_semantics=args.guard_semantics,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(source, encoding="utf-8")
    except ConversionError as error:
        print(f"fret2transitions: error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"fret2transitions: error: cannot write {args.output}: {error}", file=sys.stderr)
        return 2

    for warning in spec.warnings:
        print(f"fret2transitions: warning: {warning}", file=sys.stderr)
    print(
        f"generated {args.output} ({len(spec.states)} states, "
        f"{len(spec.transitions)} transitions)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
