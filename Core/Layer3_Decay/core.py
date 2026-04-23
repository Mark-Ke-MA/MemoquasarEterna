#!/usr/bin/env python3
from __future__ import annotations

from datetime import timedelta

from Core.Layer3_Decay.shared import LoadConfig, monday_of_iso_week

PHASE1_NAME = 'Phase1_trimL2'
PHASE1_ALLOWED_STAGES = ('Stage1', 'Stage2', 'Stage3')
PHASE1_SKIP_REASONS = {
    'status_not_archived',
    'already_trimmed',
    'missing_l1_and_nocontent',
    'invalid_l1_schema',
    'invalid_l2_schema',
}


def trim_l2_boundary_date(target_week: str, repo_root=None):
    cfg = LoadConfig(repo_root).overall_config
    layer3_decay = cfg.get('layer3_decay')
    if not isinstance(layer3_decay, dict):
        raise KeyError('OverallConfig.json 缺少 layer3_decay')
    if str(layer3_decay.get('_interval_in_units', '')) != 'week':
        raise ValueError("当前仅支持 layer3_decay._interval_in_units = 'week'")
    if 'trimL2_interval' not in layer3_decay:
        raise KeyError('OverallConfig.json.layer3_decay 缺少 trimL2_interval')
    trim_interval = int(layer3_decay.get('trimL2_interval') or 0)
    return monday_of_iso_week(target_week) - timedelta(days=7 * trim_interval + 1)


__all__ = [
    'PHASE1_NAME',
    'PHASE1_ALLOWED_STAGES',
    'PHASE1_SKIP_REASONS',
    'trim_l2_boundary_date',
]
