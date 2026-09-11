# FRET to `transitions` converter

`fret2transitions` converts a JSON export of FRETish finite-state-machine
requirements into an importable Python module backed by
[`transitions`](https://github.com/pytransitions/transitions).

The converter itself uses only the Python standard library. The generated
module requires `transitions`:

```bash
python3 -m pip install -r tools/fret2transitions/requirements.txt
```

## Usage

Run the converter from the repository root:

```bash
python3 tools/fret2transitions \
  statemachine_cases/HandsOn/fretRequirementsVariables.json \
  --output turnstile_machine.py \
  --strict
```

Use the generated module:

```python
from turnstile_machine import TurnstileMachine

machine = TurnstileMachine()
assert machine.state == "0"

# Each call advances one FRET timepoint.
assert machine.update(coin=False, push=False) == "0"
assert machine.update(coin=True, push=False) == "1"
assert machine.update(coin=False, push=True) == "0"
```

The default `rising` guard semantics implements FRETish `Upon`: a transition
is enabled when its complete source-and-guard condition changes from false to
true. Each FRETish guard is emitted as a named method and registered with
`transitions.Machine` through the transition's `conditions` argument.
Conventional level-sensitive guards can be requested explicitly:

```bash
python3 tools/fret2transitions input.json -o machine.py --guard-semantics level
```

## Supported FRETish subset

- one flat state machine and one state variable per generated class;
- `Upon (state = SOURCE & GUARD) ... at the next timepoint ... state = DEST`;
- `preBool(false, state = S & !(OUTGOING_GUARDS))` state retention;
- one `initially satisfy state = INITIAL` requirement;
- an optional `always satisfy (state = S0 | state = S1 | ...)` domain;
- Boolean guards using `!`, `&`, `|`, comparisons, and parentheses.

The combined requirements-and-variables FRET export is preferred. A
requirements-only array is accepted, but guard variables are then inferred as
Boolean inputs. Timed transitions, hierarchical or concurrent machines, and
arbitrary FRETish response expressions are rejected in strict mode.

`--strict` also requires a `State Transition Stay Pre` requirement for every
state. Without it, a missing retention requirement is reported as a warning
and the generated machine uses the normal implicit stay behavior.

The generator never evaluates raw FRETish text as Python. It parses guards
into a restricted expression tree and emits code only from validated nodes.

## Tests

```bash
python3 -m unittest discover -s tools/fret2transitions/tests -v
```
