"""Generate an importable Python module backed by pytransitions."""

from __future__ import annotations

import keyword
import pprint
import re

from .errors import ConversionError
from .model import StateMachineSpec


def _identifier(value: str, *, prefix: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_").lower()
    if not result or result[0].isdigit() or keyword.iskeyword(result):
        result = f"{prefix}_{result}"
    return result


def _class_name(component: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", component)
    result = "".join(word[:1].upper() + word[1:] for word in words)
    if not result:
        result = "Generated"
    if result[0].isdigit():
        result = "Component" + result
    return result + "Machine"


def _trigger_names(spec: StateMachineSpec) -> dict[str, str]:
    names: dict[str, str] = {}
    used: set[str] = set()
    for transition in spec.transitions:
        base = "_fire_" + _identifier(transition.reqid, prefix="requirement")
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        names[transition.reqid] = candidate
        used.add(candidate)
    return names


def generate_module(
    spec: StateMachineSpec,
    *,
    class_name: str | None = None,
    guard_semantics: str = "rising",
) -> str:
    """Return Python source implementing *spec* with ``transitions.Machine``."""

    if guard_semantics not in {"rising", "level"}:
        raise ConversionError("guard semantics must be 'rising' or 'level'")
    class_name = class_name or _class_name(spec.component)
    if not class_name.isidentifier() or keyword.iskeyword(class_name):
        raise ConversionError(f"invalid Python class name: {class_name!r}")

    trigger_names = _trigger_names(spec)
    activation_names = {
        reqid: trigger.replace("_fire_", "_activation_", 1)
        for reqid, trigger in trigger_names.items()
    }
    condition_names = {
        reqid: trigger.replace("_fire_", "_condition_", 1)
        for reqid, trigger in trigger_names.items()
    }
    rules = [
        {
            "reqid": transition.reqid,
            "source": transition.source,
            "destination": transition.destination,
            "trigger": trigger_names[transition.reqid],
            "activation": activation_names[transition.reqid],
            "conditions": condition_names[transition.reqid],
        }
        for transition in spec.transitions
    ]
    input_types = {item.name: item.data_type for item in spec.inputs}
    source_requirements = dict(spec.source_requirements)
    transition_rule_lines = ["    TRANSITION_RULES = ("]
    for rule in rules:
        transition_rule_lines.extend(
            [
                "        {",
                *(f"            {name!r}: {value!r}," for name, value in rule.items()),
                "        },",
            ]
        )
    transition_rule_lines.append("    )")

    lines = [
        '"""Generated from FRETish state-machine requirements. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Mapping",
        "",
        "from transitions import Machine",
        "",
        "",
        "class AmbiguousTransitionError(RuntimeError):",
        '    """Raised when requirements enable conflicting destinations."""',
        "",
        "",
        f"class {class_name}:",
        f"    COMPONENT = {spec.component!r}",
        f"    STATE_VARIABLE = {spec.state_variable!r}",
        f"    INITIAL_STATE = {spec.initial_state!r}",
        f"    STATES = {list(spec.states)!r}",
        f"    INPUT_TYPES = {pprint.pformat(input_types, width=88, sort_dicts=False)}",
        "    SOURCE_REQUIREMENTS = {",
        *(
            f"        {reqid!r}: {fulltext!r},"
            for reqid, fulltext in source_requirements.items()
        ),
        "    }",
        *transition_rule_lines,
        "",
        "    def __init__(self) -> None:",
        "        self.machine = Machine(",
        "            model=self,",
        "            states=self.STATES,",
        "            initial=self.INITIAL_STATE,",
        "            auto_transitions=False,",
        "            ignore_invalid_triggers=False,",
        "        )",
        "        for rule in self.TRANSITION_RULES:",
        "            self.machine.add_transition(",
        "                trigger=rule['trigger'],",
        "                source=rule['source'],",
        "                dest=rule['destination'],",
        "                conditions=rule['conditions'],",
        "            )",
        "        self._previous_activation = {",
        "            rule['reqid']: False for rule in self.TRANSITION_RULES",
        "        }",
        "        self.last_fired_requirements: tuple[str, ...] = ()",
        "",
        "    @classmethod",
        "    def _validate_inputs(cls, inputs: Mapping[str, object]) -> None:",
        "        expected = set(cls.INPUT_TYPES)",
        "        actual = set(inputs)",
        "        missing = sorted(expected - actual)",
        "        unexpected = sorted(actual - expected)",
        "        if missing or unexpected:",
        "            details = []",
        "            if missing:",
        "                details.append('missing: ' + ', '.join(missing))",
        "            if unexpected:",
        "                details.append('unexpected: ' + ', '.join(unexpected))",
        "            raise ValueError('invalid inputs (' + '; '.join(details) + ')')",
        "        for name, data_type in cls.INPUT_TYPES.items():",
        "            value = inputs[name]",
        "            if data_type == 'boolean' and type(value) is not bool:",
        "                raise TypeError(f'{name} must be boolean')",
        "            if data_type in {'integer', 'unsigned integer'} and type(value) is not int:",
        "                raise TypeError(f'{name} must be integer')",
        "            if data_type in {'single', 'double'} and (",
        "                isinstance(value, bool) or not isinstance(value, (int, float))",
        "            ):",
        "                raise TypeError(f'{name} must be numeric')",
        "            if data_type == 'unsigned integer' and value < 0:",
        "                raise ValueError(f'{name} must be non-negative')",
        "",
    ]

    for transition in spec.transitions:
        activation = activation_names[transition.reqid]
        condition = condition_names[transition.reqid]
        guard = transition.guard.to_python("inputs")
        lines.extend(
            [
                f"    def {activation}(self, **inputs: object) -> bool:",
                f'        """Evaluate the complete activation for {transition.reqid}."""',
                "",
                "        return (",
                f"            self.state == {transition.source!r} and bool({guard})",
                "        )",
                "",
                f"    def {condition}(self, **inputs: object) -> bool:",
                f'        """Evaluate the transition condition for {transition.reqid}."""',
                "",
            ]
        )
        if guard_semantics == "rising":
            lines.extend(
                [
                    f"        return self.{activation}(**inputs) and not (",
                    f"            self._previous_activation[{transition.reqid!r}]",
                    "        )",
                ]
            )
        else:
            lines.append(f"        return self.{activation}(**inputs)")
        lines.append("")

    lines.extend(
        [
            "    def update(self, **inputs: object) -> str:",
            '        """Advance one FRET timepoint and return the new state."""',
            "",
            "        self._validate_inputs(inputs)",
            "        state_at_start = self.state",
            "        activations = {",
            "            rule['reqid']: getattr(self, rule['activation'])(**inputs)",
            "            for rule in self.TRANSITION_RULES",
            "        }",
            "",
            "        enabled = [",
            "            rule",
            "            for rule in self.TRANSITION_RULES",
            "            if self.may_trigger(rule['trigger'], **inputs)",
            "        ]",
        ]
    )
    lines.extend(
        [
            "        destinations = {rule['destination'] for rule in enabled}",
            "        if len(destinations) > 1:",
            "            reqids = [rule['reqid'] for rule in enabled]",
            "            raise AmbiguousTransitionError(",
            "                f'conflicting requirements from state {state_at_start}: {reqids}'",
            "            )",
            "",
            "        self.last_fired_requirements = tuple(rule['reqid'] for rule in enabled)",
            "        if enabled:",
            "            getattr(self, enabled[0]['trigger'])(**inputs)",
            "        self._previous_activation = activations",
            "        return self.state",
            "",
            "",
            f"__all__ = ['AmbiguousTransitionError', '{class_name}']",
            "",
        ]
    )
    return "\n".join(lines)
