"""Load FRET exports and build a validated finite-state-machine IR."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

from .errors import ConversionError, ExpressionSyntaxError
from .expression import (
    Expr,
    Literal,
    Not,
    assignment,
    canonical,
    extract_source,
    flatten,
    join,
    parse_expression,
)
from .model import (
    DomainSpec,
    InitialSpec,
    StateMachineSpec,
    StaySpec,
    TransitionSpec,
    VariableSpec,
)


Requirement = Mapping[str, object]
Variable = Mapping[str, object]


@dataclass(frozen=True)
class FretExport:
    requirements: tuple[Requirement, ...]
    variables: tuple[Variable, ...]


def load_fret_export(path: str | Path) -> FretExport:
    """Load either a requirements array or a requirements-and-variables export."""

    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConversionError(f"cannot read {source}: {error}") from error
    except json.JSONDecodeError as error:
        raise ConversionError(
            f"invalid JSON in {source} at line {error.lineno}, column {error.colno}: "
            f"{error.msg}"
        ) from error

    if isinstance(data, list):
        requirements = data
        variables: list[object] = []
    elif isinstance(data, dict):
        requirements = data.get("requirements")
        variables = data.get("variables", [])
        if not isinstance(requirements, list):
            raise ConversionError("JSON object must contain a 'requirements' array")
        if not isinstance(variables, list):
            raise ConversionError("JSON field 'variables' must be an array")
    else:
        raise ConversionError("FRET export must be an array or JSON object")

    if not all(isinstance(item, dict) for item in requirements):
        raise ConversionError("every requirement must be a JSON object")
    if not all(isinstance(item, dict) for item in variables):
        raise ConversionError("every variable must be a JSON object")
    return FretExport(tuple(requirements), tuple(variables))


def _semantics(requirement: Requirement) -> Mapping[str, object]:
    value = requirement.get("semantics", {})
    return value if isinstance(value, dict) else {}


def _reqid(requirement: Requirement) -> str:
    value = requirement.get("reqid")
    if not isinstance(value, str) or not value.strip():
        raise ConversionError("every requirement must have a non-empty 'reqid'")
    return value.strip()


def _fulltext(requirement: Requirement) -> str:
    value = requirement.get("fulltext")
    if not isinstance(value, str) or not value.strip():
        raise ConversionError(f"requirement {_reqid(requirement)} has no FRETish fulltext")
    return value.strip()


def _component(requirement: Requirement) -> str | None:
    semantics = _semantics(requirement)
    value = semantics.get("component_name") or semantics.get("component")
    return value.strip() if isinstance(value, str) and value.strip() else None


def discover_components(requirements: Sequence[Requirement]) -> tuple[str, ...]:
    components = {_component(requirement) for requirement in requirements}
    return tuple(sorted(component for component in components if component))


def _post_condition(requirement: Requirement) -> str:
    value = _semantics(requirement).get("post_condition")
    if not isinstance(value, str) or not value.strip():
        raise ConversionError(
            f"requirement {_reqid(requirement)} has no parsed post_condition; "
            "recalculate its semantics in FRET before exporting"
        )
    return value


def _parse_initial(requirement: Requirement, component: str) -> InitialSpec:
    try:
        state_variable, state = assignment(parse_expression(_post_condition(requirement)))
    except ExpressionSyntaxError as error:
        raise ConversionError(f"{_reqid(requirement)}: invalid initial state: {error}") from error
    return InitialSpec(_reqid(requirement), component, state_variable, state)


def _parse_transition(requirement: Requirement, component: str) -> TransitionSpec:
    semantics = _semantics(requirement)
    condition = semantics.get("regular_condition") or semantics.get("pre_condition")
    if not isinstance(condition, str) or not condition.strip():
        raise ConversionError(
            f"{_reqid(requirement)}: next-state transition has no regular_condition"
        )
    try:
        state_variable, destination = assignment(
            parse_expression(_post_condition(requirement))
        )
        source, guard = extract_source(parse_expression(condition), state_variable)
    except ExpressionSyntaxError as error:
        raise ConversionError(f"{_reqid(requirement)}: invalid transition: {error}") from error
    return TransitionSpec(
        reqid=_reqid(requirement),
        component=component,
        state_variable=state_variable,
        source=source,
        destination=destination,
        guard=guard,
        fulltext=_fulltext(requirement),
    )


_STAY_PREFIX = re.compile(
    r"^(?:the\s+)?(?P<component>.+?)\s+shall\s+always\s+satisfy\s+"
    r"if\s+prebool\s*\(",
    re.IGNORECASE | re.DOTALL,
)


def _matching_parenthesis(text: str, opening: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ExpressionSyntaxError("unmatched parenthesis in preBool expression")


def _split_top_level_comma(text: str) -> tuple[str, str]:
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            return text[:index], text[index + 1 :]
    raise ExpressionSyntaxError("preBool must contain an initial value and expression")


def _parse_stay(requirement: Requirement, component: str) -> StaySpec:
    fulltext = _fulltext(requirement)
    match = _STAY_PREFIX.match(fulltext)
    if not match:
        raise ConversionError(
            f"{_reqid(requirement)}: unsupported state-retention requirement"
        )
    opening = match.end() - 1
    try:
        closing = _matching_parenthesis(fulltext, opening)
        initial, previous_expression = _split_top_level_comma(
            fulltext[opening + 1 : closing]
        )
        if initial.strip().lower() != "false":
            raise ExpressionSyntaxError("the first preBool argument must be false")
        tail = fulltext[closing + 1 :]
        then_match = re.fullmatch(r"\s*then\s+(.+?)\s*", tail, re.IGNORECASE | re.DOTALL)
        if not then_match:
            raise ExpressionSyntaxError("expected 'then state = value' after preBool")
        state_variable, retained_state = assignment(
            parse_expression(then_match.group(1))
        )
        source, hold_condition = extract_source(
            parse_expression(previous_expression), state_variable
        )
        if source != retained_state:
            raise ExpressionSyntaxError(
                f"retention changes state from {source!r} to {retained_state!r}"
            )
    except ExpressionSyntaxError as error:
        raise ConversionError(f"{_reqid(requirement)}: invalid retention: {error}") from error
    return StaySpec(
        _reqid(requirement), component, state_variable, retained_state, hold_condition
    )


def _parse_domain(requirement: Requirement, component: str) -> DomainSpec | None:
    try:
        expression = parse_expression(_post_condition(requirement))
        alternatives = flatten(expression, "or")
        parsed = [assignment(alternative) for alternative in alternatives]
    except ExpressionSyntaxError:
        return None
    if not parsed:
        return None
    state_variables = {state_variable for state_variable, _ in parsed}
    if len(state_variables) != 1:
        return None
    return DomainSpec(
        _reqid(requirement),
        component,
        parsed[0][0],
        tuple(state for _, state in parsed),
    )


ParsedRequirement = InitialSpec | TransitionSpec | StaySpec | DomainSpec


def _parse_requirement(requirement: Requirement, component: str) -> ParsedRequirement | None:
    fulltext = _fulltext(requirement)
    semantics = _semantics(requirement)
    timing = str(semantics.get("timing", "")).lower()
    condition_type = str(semantics.get("condition", "")).lower()

    if re.search(r"\bprebool\s*\(", fulltext, re.IGNORECASE):
        return _parse_stay(requirement, component)
    if re.search(r"\bshall\s+initially\s+satisfy\b", fulltext, re.IGNORECASE):
        return _parse_initial(requirement, component)
    if timing == "next" and condition_type == "regular":
        qualifier = str(semantics.get("qualifier_word", "upon")).lower()
        if qualifier != "upon":
            raise ConversionError(
                f"{_reqid(requirement)}: only Upon transitions are supported, got {qualifier!r}"
            )
        return _parse_transition(requirement, component)
    if timing == "always" and condition_type in {"", "null", "none"}:
        return _parse_domain(requirement, component)
    return None


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _variable_specs(
    variables: Sequence[Variable], component: str
) -> dict[str, VariableSpec]:
    result: dict[str, VariableSpec] = {}
    for variable in variables:
        variable_component = variable.get("component_name")
        if isinstance(variable_component, str) and variable_component != component:
            continue
        name = variable.get("variable_name")
        if not isinstance(name, str) or not name:
            continue
        spec = VariableSpec(
            name=name,
            variable_type=str(variable.get("idType", "")),
            data_type=str(variable.get("dataType", "")),
        )
        if name in result and result[name] != spec:
            raise ConversionError(f"conflicting Variable Mapping entries for {name!r}")
        result[name] = spec
    return result


def _check_overlaps(
    transitions: Sequence[TransitionSpec],
    inputs: Mapping[str, VariableSpec],
    warnings: list[str],
) -> None:
    for source in sorted({transition.source for transition in transitions}):
        outgoing = [transition for transition in transitions if transition.source == source]
        for left, right in itertools.combinations(outgoing, 2):
            if left.destination == right.destination:
                continue
            names = sorted(left.guard.identifiers() | right.guard.identifiers())
            if len(names) > 12 or any(
                inputs.get(name, VariableSpec(name, "", "")).data_type != "boolean"
                for name in names
            ):
                warnings.append(
                    f"could not statically check guard overlap between {left.reqid} and "
                    f"{right.reqid}; generated code will check it at runtime"
                )
                continue
            for values in itertools.product((False, True), repeat=len(names)):
                environment = dict(zip(names, values))
                if bool(left.guard.evaluate(environment)) and bool(
                    right.guard.evaluate(environment)
                ):
                    witness = ", ".join(
                        f"{name}={environment[name]}" for name in names
                    )
                    raise ConversionError(
                        f"conflicting transitions {left.reqid} -> {left.destination!r} and "
                        f"{right.reqid} -> {right.destination!r} from state {source!r}; "
                        f"overlap witness: {witness or 'unconditional'}"
                    )


def _check_stays(
    states: Sequence[str],
    transitions: Sequence[TransitionSpec],
    stays: Sequence[StaySpec],
    strict: bool,
    warnings: list[str],
) -> None:
    by_state: dict[str, list[StaySpec]] = {}
    for stay in stays:
        by_state.setdefault(stay.state, []).append(stay)
    for state in states:
        entries = by_state.get(state, [])
        if len(entries) > 1:
            raise ConversionError(
                f"state {state!r} has multiple retention requirements: "
                + ", ".join(entry.reqid for entry in entries)
            )
        if not entries:
            message = (
                f"state {state!r} has no State Transition Stay Pre requirement; "
                "generated code will retain the state implicitly"
            )
            if strict:
                raise ConversionError(message)
            warnings.append(message)
            continue
        outgoing_guards = [
            transition.guard
            for transition in transitions
            if transition.source == state
        ]
        expected = Not(join("or", outgoing_guards)) if outgoing_guards else Literal(True)
        if canonical(entries[0].hold_condition) != canonical(expected):
            raise ConversionError(
                f"{entries[0].reqid}: retention guard for state {state!r} is not the "
                "negation of all outgoing transition guards"
            )


def _check_reachability(
    states: Sequence[str],
    initial: str,
    transitions: Sequence[TransitionSpec],
    warnings: list[str],
) -> None:
    reachable = {initial}
    changed = True
    while changed:
        changed = False
        for transition in transitions:
            if transition.source in reachable and transition.destination not in reachable:
                reachable.add(transition.destination)
                changed = True
    unreachable = [state for state in states if state not in reachable]
    if unreachable:
        warnings.append(
            "structurally unreachable states: " + ", ".join(repr(state) for state in unreachable)
        )


def build_state_machine(
    requirements: Sequence[Requirement],
    variables: Sequence[Variable] = (),
    *,
    component: str | None = None,
    state_variable: str | None = None,
    initial_state: str | None = None,
    strict: bool = False,
) -> StateMachineSpec:
    """Convert exported FRET requirements into a checked state-machine IR."""

    if not requirements:
        raise ConversionError("the FRET export contains no requirements")
    components = discover_components(requirements)
    if component is None:
        if len(components) != 1:
            detail = ", ".join(components) or "none"
            raise ConversionError(
                f"expected exactly one component, found {detail}; use --component"
            )
        component = components[0]
    elif components and component not in components:
        raise ConversionError(
            f"component {component!r} not found; available: {', '.join(components)}"
        )

    selected = [
        requirement
        for requirement in requirements
        if _component(requirement) in {None, component}
    ]
    parsed: list[ParsedRequirement] = []
    warnings: list[str] = []
    seen_reqids: set[str] = set()
    for requirement in selected:
        reqid = _reqid(requirement)
        if reqid in seen_reqids:
            raise ConversionError(f"duplicate requirement id: {reqid}")
        seen_reqids.add(reqid)
        item = _parse_requirement(requirement, component)
        if item is None:
            message = f"{reqid}: requirement is outside the supported FSM subset"
            if strict:
                raise ConversionError(message)
            warnings.append(message)
        else:
            parsed.append(item)

    transitions = [item for item in parsed if isinstance(item, TransitionSpec)]
    initials = [item for item in parsed if isinstance(item, InitialSpec)]
    stays = [item for item in parsed if isinstance(item, StaySpec)]
    domains = [item for item in parsed if isinstance(item, DomainSpec)]
    if not transitions:
        raise ConversionError(f"component {component!r} contains no next-state transitions")

    inferred_variables = {
        item.state_variable
        for item in parsed
        if isinstance(item, (InitialSpec, TransitionSpec, StaySpec, DomainSpec))
    }
    if state_variable is None:
        if len(inferred_variables) != 1:
            raise ConversionError(
                "could not infer one state variable; found "
                + ", ".join(sorted(inferred_variables))
                + "; use --state-variable"
            )
        state_variable = next(iter(inferred_variables))
    mismatched = [
        item
        for item in parsed
        if isinstance(item, (InitialSpec, TransitionSpec, StaySpec, DomainSpec))
        and item.state_variable != state_variable
    ]
    if mismatched:
        raise ConversionError(
            f"requirements use state variables other than {state_variable!r}: "
            + ", ".join(item.reqid for item in mismatched)
        )

    if initial_state is None:
        if len(initials) != 1:
            raise ConversionError(
                f"expected exactly one initial-state requirement, found {len(initials)}; "
                "use --initial to override"
            )
        initial_state = initials[0].state
    elif initials and any(item.state != initial_state for item in initials):
        raise ConversionError(
            f"--initial {initial_state!r} conflicts with FRET initial-state requirement"
        )

    domain_states: tuple[str, ...] = ()
    if domains:
        domain_states = domains[0].states
        if any(set(domain.states) != set(domain_states) for domain in domains[1:]):
            raise ConversionError("multiple state-domain requirements disagree")
    discovered_states = _ordered_unique(
        [initial_state]
        + [value for transition in transitions for value in (transition.source, transition.destination)]
        + [stay.state for stay in stays]
    )
    if domain_states:
        unknown = set(discovered_states) - set(domain_states)
        if unknown:
            raise ConversionError(
                "transitions reference states outside the declared domain: "
                + ", ".join(sorted(unknown))
            )
        states = _ordered_unique(domain_states)
    else:
        states = discovered_states
        warnings.append("no state-domain requirement found; states were inferred from transitions")

    mapped_variables = _variable_specs(variables, component)
    if mapped_variables:
        mapped_state = mapped_variables.get(state_variable)
        if mapped_state is None:
            raise ConversionError(
                f"state variable {state_variable!r} is missing from Variable Mapping"
            )
        if mapped_state.variable_type != "Output":
            raise ConversionError(
                f"state variable {state_variable!r} must be Output, got "
                f"{mapped_state.variable_type or 'None'}"
            )

    guard_names = sorted(
        set().union(*(transition.guard.identifiers() for transition in transitions))
    )
    input_specs: list[VariableSpec] = []
    for name in guard_names:
        mapped = mapped_variables.get(name)
        if mapped_variables and mapped is None:
            raise ConversionError(f"guard variable {name!r} is missing from Variable Mapping")
        if mapped and mapped.variable_type != "Input":
            raise ConversionError(
                f"guard variable {name!r} must be Input, got "
                f"{mapped.variable_type or 'None'}"
            )
        input_specs.append(mapped or VariableSpec(name, "Input", "boolean"))
    if not mapped_variables:
        warnings.append("no Variable Mapping found; all guard variables were inferred as boolean Inputs")

    input_map = {item.name: item for item in input_specs}
    _check_overlaps(transitions, input_map, warnings)
    _check_stays(states, transitions, stays, strict, warnings)
    _check_reachability(states, initial_state, transitions, warnings)

    source_requirements = {
        _reqid(requirement): _fulltext(requirement)
        for requirement in selected
        if _reqid(requirement) in {item.reqid for item in parsed}
    }
    return StateMachineSpec(
        component=component,
        state_variable=state_variable,
        initial_state=initial_state,
        states=states,
        inputs=tuple(input_specs),
        transitions=tuple(transitions),
        stays=tuple(stays),
        source_requirements=source_requirements,
        warnings=tuple(warnings),
    )
