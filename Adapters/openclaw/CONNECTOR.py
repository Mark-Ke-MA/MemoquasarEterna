from __future__ import annotations

from . import openclaw_call_LLM, openclaw_runtime_maintenance
from .Extract.core import fetch_openclaw_layer0_input
from .Installation.PREREQUISITES import run_prerequisites as prerequisites_entry
from .Installation.INSTALL import run_install as install_entry
from .Installation.UNINSTALL import run_uninstall as uninstall_entry
from .Sessions_Watch.Preserve.entry import entry as sessions_watch_preserve_entry
from .Sessions_Watch.Decay.entry import entry as sessions_watch_decay_entry

OPENCLAW_NEW_CONNECTOR = {
    'call_llm': openclaw_call_LLM.openclaw_call_subagent_readandwrite,
    'prerequisites': prerequisites_entry,
    'install': install_entry,
    'uninstall': uninstall_entry,
    'extract': fetch_openclaw_layer0_input,
    'harness_clean': openclaw_runtime_maintenance.openclaw_harness_maintenance_hook,
    'harness_preserve': sessions_watch_preserve_entry,
    'harness_decay': sessions_watch_decay_entry,
}

CONNECTOR = OPENCLAW_NEW_CONNECTOR
