from __future__ import annotations

from .Extract.core import fetch_hermes_layer0_input


def _not_implemented(*args, **kwargs):
    raise NotImplementedError('Hermes adapter first phase only implements production_agent.extract')


CONNECTOR = {
    'ensure_config': _not_implemented,
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
        'prerequisites': _not_implemented,
        'install': _not_implemented,
        'uninstall': _not_implemented,
    },
}
