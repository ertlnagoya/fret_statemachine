"""Intermediate representation used by the converter."""

from __future__ import annotations

from dataclasses import dataclass, field

from .expression import Expr


@dataclass(frozen=True)
class VariableSpec:
    name: str
    variable_type: str
    data_type: str


@dataclass(frozen=True)
class InitialSpec:
    reqid: str
    component: str
    state_variable: str
    state: str


@dataclass(frozen=True)
class TransitionSpec:
    reqid: str
    component: str
    state_variable: str
    source: str
    destination: str
    guard: Expr
    fulltext: str


@dataclass(frozen=True)
class StaySpec:
    reqid: str
    component: str
    state_variable: str
    state: str
    hold_condition: Expr


@dataclass(frozen=True)
class DomainSpec:
    reqid: str
    component: str
    state_variable: str
    states: tuple[str, ...]


@dataclass(frozen=True)
class StateMachineSpec:
    component: str
    state_variable: str
    initial_state: str
    states: tuple[str, ...]
    inputs: tuple[VariableSpec, ...]
    transitions: tuple[TransitionSpec, ...]
    stays: tuple[StaySpec, ...]
    source_requirements: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

