"""Which customer agent answers: the agent loop (default) or the supervisor graph kept as a fallback (W3.2-D11).

The choice is configuration only: `RETAILOPS_AGENT_MODE=legacy` in the environment file and a restart bring the
old graph back, `agent` (or nothing) selects the new loop. This module imports nothing heavy so that startup
validation (`retailops.config`) and the application share one definition.
"""
import os

AGENT_MODES = ('agent', 'legacy')
_OLD_NAMES = {'single_agent': 'agent', 'multi_agent': 'legacy'}  # RETAILOPS_ORCHESTRATOR and `orchestrator=` before W3.2


def resolve_agent_mode(requested=None, environ=None):
    """'agent' or 'legacy'. Precedence: the caller, RETAILOPS_AGENT_MODE, the older RETAILOPS_ORCHESTRATOR, then 'agent'.

    A value that is none of these stops startup instead of silently choosing a mode.
    """
    env = os.environ if environ is None else environ
    value = str(requested or env.get('RETAILOPS_AGENT_MODE', '') or env.get('RETAILOPS_ORCHESTRATOR', '') or 'agent')
    value = value.strip().lower()
    value = _OLD_NAMES.get(value, value)
    if value not in AGENT_MODES:
        raise ValueError('RETAILOPS_AGENT_MODE must be agent or legacy.')
    return value
