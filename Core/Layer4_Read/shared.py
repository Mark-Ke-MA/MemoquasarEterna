#!/usr/bin/env python3
from __future__ import annotations

"""Shared helpers for Layer4_Read."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class L0Anchor:
    depth: str
    time_key: str
    score: float


__all__ = ['L0Anchor']
