from __future__ import annotations

import copy
import sys
import types
import unittest
from pathlib import Path


TOOLS_DIRECTORY = Path(__file__).resolve().parents[2]
if str(TOOLS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIRECTORY))

from fret2transitions import (  # noqa: E402
    ConversionError,
    build_state_machine,
    generate_module,
    load_fret_export,
)
from fret2transitions.expression import parse_expression  # noqa: E402


FRET_ROOT = Path(__file__).resolve().parents[3]
TURNSTILE_EXPORT = (
    FRET_ROOT / "statemachine_cases" / "HandsOn" / "fretRequirementsVariables.json"
)


class FakeMachine:
    """The small part of transitions.Machine needed for generated-code tests."""

    def __init__(self, model, states, initial, **_options):
        self.model = model
        self.states = states
        self.transitions = {}
        model.state = initial
        model.may_trigger = self.may_trigger

    def _conditions_pass(self, conditions, inputs):
        callbacks = [conditions] if isinstance(conditions, str) else conditions or []
        return all(
            getattr(self.model, callback)(**inputs)
            if isinstance(callback, str)
            else callback(**inputs)
            for callback in callbacks
        )

    def may_trigger(self, trigger, **inputs):
        transition = self.transitions[trigger]
        return self.model.state == transition["source"] and self._conditions_pass(
            transition["conditions"], inputs
        )

    def add_transition(self, trigger, source, dest, conditions=None):
        model = self.model
        self.transitions[trigger] = {
            "source": source,
            "destination": dest,
            "conditions": conditions,
        }

        def fire(**inputs):
            if model.state != source:
                raise RuntimeError(f"cannot fire {trigger} from {model.state}")
            if not self._conditions_pass(conditions, inputs):
                return False
            model.state = dest
            return True

        setattr(model, trigger, fire)


class ConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exported = load_fret_export(TURNSTILE_EXPORT)

    def build_turnstile(self, **options):
        return build_state_machine(
            self.exported.requirements,
            self.exported.variables,
            strict=True,
            **options,
        )

    def test_real_fret_export_is_converted(self):
        spec = self.build_turnstile()

        self.assertEqual(spec.component, "turnstile")
        self.assertEqual(spec.state_variable, "state")
        self.assertEqual(spec.initial_state, "0")
        self.assertEqual(spec.states, ("0", "1"))
        self.assertEqual(
            {(item.source, item.destination) for item in spec.transitions},
            {("0", "1"), ("1", "0")},
        )
        self.assertEqual(
            {(item.name, item.variable_type, item.data_type) for item in spec.inputs},
            {
                ("coin", "Input", "boolean"),
                ("push", "Input", "boolean"),
            },
        )
        self.assertEqual(spec.warnings, ())

    def test_generated_source_is_valid_python(self):
        source = generate_module(self.build_turnstile())
        compile(source, "turnstile_machine.py", "exec")
        self.assertIn("class TurnstileMachine", source)
        self.assertIn("auto_transitions=False", source)
        self.assertIn("conditions=rule['conditions']", source)
        self.assertIn("def update(self", source)
        self.assertNotIn("eval(", source)

    def test_generated_machine_follows_turnstile_trace(self):
        source = generate_module(self.build_turnstile())
        fake_module = types.ModuleType("transitions")
        fake_module.Machine = FakeMachine
        previous = sys.modules.get("transitions")
        sys.modules["transitions"] = fake_module
        namespace = {"__name__": "generated_turnstile"}
        try:
            exec(compile(source, "turnstile_machine.py", "exec"), namespace)
        finally:
            if previous is None:
                del sys.modules["transitions"]
            else:
                sys.modules["transitions"] = previous

        machine = namespace["TurnstileMachine"]()
        self.assertEqual(machine.state, "0")
        self.assertEqual(machine.update(coin=False, push=False), "0")
        self.assertEqual(machine.update(coin=True, push=False), "1")
        self.assertEqual(machine.last_fired_requirements, ("TS-002",))
        self.assertEqual(machine.update(coin=False, push=True), "0")
        self.assertEqual(machine.last_fired_requirements, ("TS-003",))

        with self.assertRaisesRegex(ValueError, "missing: push"):
            machine.update(coin=False)
        with self.assertRaisesRegex(TypeError, "coin must be boolean"):
            machine.update(coin=1, push=False)

    def test_registered_condition_guards_direct_trigger(self):
        source = generate_module(self.build_turnstile())
        fake_module = types.ModuleType("transitions")
        fake_module.Machine = FakeMachine
        previous = sys.modules.get("transitions")
        sys.modules["transitions"] = fake_module
        namespace = {"__name__": "generated_turnstile"}
        try:
            exec(compile(source, "turnstile_machine.py", "exec"), namespace)
        finally:
            if previous is None:
                del sys.modules["transitions"]
            else:
                sys.modules["transitions"] = previous

        machine = namespace["TurnstileMachine"]()
        self.assertEqual(
            machine.machine.transitions["_fire_ts_002"]["conditions"],
            "_condition_ts_002",
        )
        self.assertFalse(machine._fire_ts_002(coin=False, push=False))
        self.assertEqual(machine.state, "0")
        self.assertTrue(machine._fire_ts_002(coin=True, push=False))
        self.assertEqual(machine.state, "1")

    def test_conflicting_guards_are_rejected(self):
        requirements = list(self.exported.requirements)
        original = next(item for item in requirements if item["reqid"] == "TS-002")
        conflict = copy.deepcopy(original)
        conflict["reqid"] = "TS-007"
        conflict["fulltext"] = (
            "Upon (state = 0 & coin) the turnstile shall at the next timepoint "
            "satisfy state = 0"
        )
        conflict["semantics"]["post_condition"] = "(state = 0)"
        requirements.append(conflict)

        with self.assertRaisesRegex(ConversionError, "conflicting transitions"):
            build_state_machine(requirements, self.exported.variables, strict=True)

    def test_strict_mode_rejects_missing_retention(self):
        requirements = [
            item for item in self.exported.requirements if item["reqid"] != "TS-005"
        ]
        with self.assertRaisesRegex(ConversionError, "no State Transition Stay Pre"):
            build_state_machine(requirements, self.exported.variables, strict=True)

        spec = build_state_machine(requirements, self.exported.variables, strict=False)
        self.assertTrue(any("no State Transition Stay Pre" in item for item in spec.warnings))

    def test_unsafe_function_syntax_is_not_accepted(self):
        with self.assertRaises(ConversionError):
            parse_expression("__import__('os').system('echo unsafe')")


if __name__ == "__main__":
    unittest.main()
