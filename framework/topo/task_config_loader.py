"""Load and query task_config.yaml for per-task verification parameters.

Provides a thin API so phase2_checks, rule_checker, and match_skeleton
can look up task-specific flags without hardcoding task_id sets.
"""

import os
import yaml

# --- Shared task-complexity constants ---
# Used by run.py, run_rex.py, and prompt template selection.
COMPLEX_POWER_TASKS = set(range(17, 24))
COMPLEX_UNIVERSAL_TASKS = {49, 50, 51, 52, 54, 55, 62, 64, 65, 66, 67, 68}

_CONFIG = None
_DEFAULTS = {
    "match_mode": "relaxed",
    "graph_tolerance": 0,
    "passive_tolerance": 0.0,
    "checks": [],
    "skip_rules": [],
    "skip_component_count": [],
}


def _load():
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    config_path = os.path.join(os.path.dirname(__file__), "..", "task_config.yaml")
    config_path = os.path.abspath(config_path)
    with open(config_path) as f:
        _CONFIG = yaml.safe_load(f)
    return _CONFIG


def get_task(task_id):
    """Return merged config dict for a task (defaults + task overrides)."""
    cfg = _load()
    defaults = cfg.get("defaults", _DEFAULTS)
    tasks = cfg.get("tasks", {})
    task_cfg = tasks.get(task_id, {})
    merged = {**_DEFAULTS, **defaults, **task_cfg}
    return merged


def has_check(task_id, check_name):
    """Check if a task enables a specific check group."""
    return check_name in get_task(task_id).get("checks", [])


def has_skip_rule(task_id, rule_name):
    """Check if a task skips a specific rule."""
    return rule_name in get_task(task_id).get("skip_rules", [])


def get_match_mode(task_id):
    """Return match mode: full_subgraph | key_subgraph | relaxed."""
    return get_task(task_id).get("match_mode", "relaxed")


def get_graph_tolerance(task_id):
    return get_task(task_id).get("graph_tolerance", 0)


def get_passive_tolerance(task_id):
    return get_task(task_id).get("passive_tolerance", 0.0)


def skip_component_count(task_id, part_id):
    return part_id in get_task(task_id).get("skip_component_count", [])
