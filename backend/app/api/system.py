"""Operational endpoints used by the public JevFish demo."""

import json
import os
import re

from flask import jsonify

from . import system_bp
from ..config import Config
from ..services.simulation_runner import SimulationRunner


_SIMULATION_ID = re.compile(r'^[A-Za-z0-9_-]+$')


def _read_json(path: str) -> dict | None:
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _active_simulations() -> int:
    return sum(
        1 for process in SimulationRunner._processes.values()
        if process is not None and process.poll() is None
    )


def _merge_max_counts(target: dict[str, float], source: dict | None) -> None:
    """Merge a cumulative shared-engine snapshot without double-counting it."""
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        if isinstance(value, (int, float)):
            name = str(key)
            target[name] = max(float(target.get(name, 0)), float(value))


@system_bp.route('/status', methods=['GET'])
def system_status():
    """Return non-secret operational state for the demo UI."""
    active = _active_simulations()
    return jsonify({
        'success': True,
        'data': {
            'service': 'JevFish',
            'environment': Config.APP_ENV,
            'decision_engine': Config.JEVFISH_DECISION_ENGINE,
            'jev_model': Config.TYPESAFE_DEFAULT_MODEL,
            'llm_model': Config.LLM_MODEL_NAME,
            'observation_mode': Config.JEVFISH_OBSERVATION_MODE,
            'active_simulations': active,
            'max_concurrent_simulations': Config.MAX_CONCURRENT_SIMULATIONS,
            'at_capacity': active >= Config.MAX_CONCURRENT_SIMULATIONS,
        },
    })


@system_bp.route('/simulations/<simulation_id>/metrics', methods=['GET'])
def simulation_metrics(simulation_id: str):
    """Return the latest cumulative JevFish snapshot for a simulation.

    Parallel Twitter/Reddit environments share one JevDecisionEngine in the
    current runner. Each platform file is therefore a snapshot of the same
    monotonic counters at a different instant. Taking the maximum per counter
    yields the latest shared total; summing the files would double-count work.
    """
    if not _SIMULATION_ID.fullmatch(simulation_id):
        return jsonify({'success': False, 'error': 'Invalid simulation id'}), 400

    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    if not os.path.isdir(sim_dir):
        return jsonify({'success': False, 'error': 'Simulation not found'}), 404

    platform_metrics: dict[str, dict] = {}
    for platform in ('twitter', 'reddit'):
        metrics = _read_json(os.path.join(sim_dir, f'jevfish_{platform}_metrics.json'))
        if metrics:
            platform_metrics[platform] = metrics

    run_state = _read_json(os.path.join(sim_dir, 'run_state.json')) or {}

    numeric_fields = (
        'jev_calls',
        'jev_plans',
        'jev_manual_actions',
        'llm_fallbacks',
        'llm_escalations',
        'system_two_calls',
        'system_two_requests',
        'system_two_errors',
        'passthrough_actions',
        'errors',
        'uncertain_gates',
        'observation_refreshes',
        'observation_posts',
        'observation_fallbacks',
        'observation_errors',
    )
    totals: dict[str, float] = {field: 0 for field in numeric_fields}
    manual_by_type: dict[str, float] = {}
    system_two_by_type: dict[str, float] = {}
    selected_by_type: dict[str, float] = {}

    for metrics in platform_metrics.values():
        for field in numeric_fields:
            value = metrics.get(field, 0)
            if isinstance(value, (int, float)):
                totals[field] = max(float(totals[field]), float(value))
        _merge_max_counts(manual_by_type, metrics.get('manual_by_type'))
        _merge_max_counts(system_two_by_type, metrics.get('system_two_by_type'))
        _merge_max_counts(selected_by_type, metrics.get('selected_by_type'))

    normalized_totals = {
        field: int(value) if float(value).is_integer() else value
        for field, value in totals.items()
    }
    normalized_manual = {
        key: int(value) if float(value).is_integer() else value
        for key, value in manual_by_type.items()
    }
    normalized_system_two = {
        key: int(value) if float(value).is_integer() else value
        for key, value in system_two_by_type.items()
    }
    normalized_selected = {
        key: int(value) if float(value).is_integer() else value
        for key, value in selected_by_type.items()
    }

    jev_calls = int(normalized_totals['jev_calls'])
    full_llm_turns = int(normalized_totals['llm_fallbacks'])
    system_one_turns = max(jev_calls - full_llm_turns, 0)
    system_one_share = round(system_one_turns / jev_calls * 100, 1) if jev_calls else 0.0

    data = {
        **normalized_totals,
        'system_one_turns': system_one_turns,
        'system_one_share_pct': system_one_share,
        'manual_by_type': normalized_manual,
        'system_two_by_type': normalized_system_two,
        'selected_by_type': normalized_selected,
        'platforms': platform_metrics,
        'runner_status': run_state.get('runner_status', 'unknown'),
        'current_round': run_state.get('current_round', 0),
        'total_rounds': run_state.get('total_rounds', 0),
        'decision_engine': Config.JEVFISH_DECISION_ENGINE,
        'jev_model': Config.TYPESAFE_DEFAULT_MODEL,
        'observation_mode': Config.JEVFISH_OBSERVATION_MODE,
    }

    return jsonify({'success': True, 'data': data})
