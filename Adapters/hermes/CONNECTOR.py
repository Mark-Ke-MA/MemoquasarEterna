from __future__ import annotations

from .Extract.core import fetch_hermes_layer0_input
from .Installation.ENSURE_CONFIG import run_ensure_config as ensure_config_entry
from .Installation.PRODUCTION_AGENT_INSTALL import run_install as production_agent_install_entry
from .Installation.PRODUCTION_AGENT_PREREQUISITES import run_prerequisites as production_agent_prerequisites_entry
from .Installation.PRODUCTION_AGENT_UNINSTALL import run_uninstall as production_agent_uninstall_entry


def _not_implemented(*args, **kwargs):
    raise NotImplementedError('Hermes adapter only implements experimental production_agent Layer0/Layer4 support')


CONNECTOR = {
    'ensure_config': ensure_config_entry,
    'memory_worker': {
        'call_llm': _not_implemented,
        'clean_runtime': _not_implemented,
        'prerequisites': _not_implemented,
        'install': _not_implemented,
        'uninstall': _not_implemented,
    },
    'production_agent': {
        'extract': fetch_hermes_layer0_input,
        'preserve': _not_implemented,
        'decay': _not_implemented,
        'prerequisites': production_agent_prerequisites_entry,
        'install': production_agent_install_entry,
        'uninstall': production_agent_uninstall_entry,
    },
}
