"""Generated from FRETish state-machine requirements. Do not edit by hand."""

from __future__ import annotations

from typing import Mapping

from transitions import Machine


class AmbiguousTransitionError(RuntimeError):
    """Raised when requirements enable conflicting destinations."""


class TurnstileMachine:
    COMPONENT = 'turnstile'
    STATE_VARIABLE = 'state'
    INITIAL_STATE = '0'
    STATES = ['0', '1']
    INPUT_TYPES = {'coin': 'boolean', 'push': 'boolean'}
    SOURCE_REQUIREMENTS = {
        'TS-004': 'The turnstile  shall always satisfy if preBool(false,  state = 0  & !(  coin )) then  state = 0',
        'TS-003': 'Upon ( state = 1  &  push )  the turnstile  shall at the next timepoint satisfy  state = 0',
        'TS-005': 'The turnstile  shall always satisfy if preBool(false,  state = 1  & !(  push )) then  state = 1',
        'TS-006': 'The  turnstile  shall always satisfy  (state = 0 | state = 1)',
        'TS-001': 'The turnstile shall initially satisfy state = 0',
        'TS-002': 'Upon ( state = 0  &  coin )  the turnstile  shall at the next timepoint satisfy  state = 1',
    }
    TRANSITION_RULES = (
        {
            'reqid': 'TS-003',
            'source': '1',
            'destination': '0',
            'trigger': '_fire_ts_003',
            'activation': '_activation_ts_003',
            'conditions': '_condition_ts_003',
        },
        {
            'reqid': 'TS-002',
            'source': '0',
            'destination': '1',
            'trigger': '_fire_ts_002',
            'activation': '_activation_ts_002',
            'conditions': '_condition_ts_002',
        },
    )

    def __init__(self) -> None:
        self.machine = Machine(
            model=self,
            states=self.STATES,
            initial=self.INITIAL_STATE,
            auto_transitions=False,
            ignore_invalid_triggers=False,
        )
        for rule in self.TRANSITION_RULES:
            self.machine.add_transition(
                trigger=rule['trigger'],
                source=rule['source'],
                dest=rule['destination'],
                conditions=rule['conditions'],
            )
        self._previous_activation = {
            rule['reqid']: False for rule in self.TRANSITION_RULES
        }
        self.last_fired_requirements: tuple[str, ...] = ()

    @classmethod
    def _validate_inputs(cls, inputs: Mapping[str, object]) -> None:
        expected = set(cls.INPUT_TYPES)
        actual = set(inputs)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            details = []
            if missing:
                details.append('missing: ' + ', '.join(missing))
            if unexpected:
                details.append('unexpected: ' + ', '.join(unexpected))
            raise ValueError('invalid inputs (' + '; '.join(details) + ')')
        for name, data_type in cls.INPUT_TYPES.items():
            value = inputs[name]
            if data_type == 'boolean' and type(value) is not bool:
                raise TypeError(f'{name} must be boolean')
            if data_type in {'integer', 'unsigned integer'} and type(value) is not int:
                raise TypeError(f'{name} must be integer')
            if data_type in {'single', 'double'} and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise TypeError(f'{name} must be numeric')
            if data_type == 'unsigned integer' and value < 0:
                raise ValueError(f'{name} must be non-negative')

    def _activation_ts_003(self, **inputs: object) -> bool:
        """Evaluate the complete activation for TS-003."""

        return (
            self.state == '1' and bool(inputs['push'])
        )

    def _condition_ts_003(self, **inputs: object) -> bool:
        """Evaluate the transition condition for TS-003."""

        return self._activation_ts_003(**inputs) and not (
            self._previous_activation['TS-003']
        )

    def _activation_ts_002(self, **inputs: object) -> bool:
        """Evaluate the complete activation for TS-002."""

        return (
            self.state == '0' and bool(inputs['coin'])
        )

    def _condition_ts_002(self, **inputs: object) -> bool:
        """Evaluate the transition condition for TS-002."""

        return self._activation_ts_002(**inputs) and not (
            self._previous_activation['TS-002']
        )

    def update(self, **inputs: object) -> str:
        """Advance one FRET timepoint and return the new state."""

        self._validate_inputs(inputs)
        state_at_start = self.state
        activations = {
            rule['reqid']: getattr(self, rule['activation'])(**inputs)
            for rule in self.TRANSITION_RULES
        }

        enabled = [
            rule
            for rule in self.TRANSITION_RULES
            if self.may_trigger(rule['trigger'], **inputs)
        ]
        destinations = {rule['destination'] for rule in enabled}
        if len(destinations) > 1:
            reqids = [rule['reqid'] for rule in enabled]
            raise AmbiguousTransitionError(
                f'conflicting requirements from state {state_at_start}: {reqids}'
            )

        self.last_fired_requirements = tuple(rule['reqid'] for rule in enabled)
        if enabled:
            getattr(self, enabled[0]['trigger'])(**inputs)
        self._previous_activation = activations
        return self.state


__all__ = ['AmbiguousTransitionError', 'TurnstileMachine']
