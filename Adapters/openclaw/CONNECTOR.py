from __future__ import annotations

from . import openclaw_call_LLM, openclaw_runtime_maintenance
from .Extract.core import fetch_openclaw_layer0_input
from .Installation.MEMORY_WORKER_PREREQUISITES import run_prerequisites as memory_worker_prerequisites_entry
from .Installation.MEMORY_WORKER_INSTALL import run_install as memory_worker_install_entry
from .Installation.MEMORY_WORKER_UNINSTALL import run_uninstall as memory_worker_uninstall_entry
from .Installation.PRODUCTION_AGENT_PREREQUISITES import run_prerequisites as production_agent_prerequisites_entry
from .Installation.PRODUCTION_AGENT_INSTALL import run_install as production_agent_install_entry
from .Installation.PRODUCTION_AGENT_UNINSTALL import run_uninstall as production_agent_uninstall_entry
from .Sessions_Watch.Preserve.entry import entry as sessions_watch_preserve_entry
from .Sessions_Watch.Decay.entry import entry as sessions_watch_decay_entry

OPENCLAW_NEW_CONNECTOR = {
    'memory_worker': {
        'call_llm': openclaw_call_LLM.openclaw_call_subagent_readandwrite,
        'clean_runtime': openclaw_runtime_maintenance.openclaw_harness_maintenance_hook,
        'prerequisites': memory_worker_prerequisites_entry,
        'install': memory_worker_install_entry,
        'uninstall': memory_worker_uninstall_entry,
    },
    'production_agent': {
        'extract': fetch_openclaw_layer0_input,
        'preserve': sessions_watch_preserve_entry,
        'decay': sessions_watch_decay_entry,
        'prerequisites': production_agent_prerequisites_entry,
        'install': production_agent_install_entry,
        'uninstall': production_agent_uninstall_entry,
    },
}

CONNECTOR = OPENCLAW_NEW_CONNECTOR
