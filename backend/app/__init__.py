"""JevFish Flask application factory."""

import json
import os
import time
import warnings
from collections import defaultdict, deque
from datetime import datetime
from threading import Lock

warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS

from .config import Config
from .utils.logger import get_logger, setup_logger


_rate_windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_rate_lock = Lock()


def _client_ip() -> str:
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',', 1)[0].strip()
    return request.remote_addr or 'unknown'


def _check_rate_limit(limit: int) -> bool:
    """Small single-instance sliding-window limiter for expensive demo mutations."""
    now = time.monotonic()
    key = (_client_ip(), request.path)
    with _rate_lock:
        window = _rate_windows[key]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
    return True


def _recover_interrupted_simulations(logger) -> int:
    """Fail closed for persisted runs whose owning web process disappeared."""
    if not Config.IS_PRODUCTION:
        return 0

    root = Config.OASIS_SIMULATION_DATA_DIR
    if not os.path.isdir(root):
        return 0

    active = {'starting', 'running', 'paused', 'stopping'}
    recovered = 0
    now = datetime.now().isoformat()

    for simulation_id in os.listdir(root):
        sim_dir = os.path.join(root, simulation_id)
        run_state_path = os.path.join(sim_dir, 'run_state.json')
        if not os.path.isfile(run_state_path):
            continue
        try:
            with open(run_state_path, 'r', encoding='utf-8') as handle:
                run_state = json.load(handle)
            if run_state.get('runner_status') not in active:
                continue

            message = (
                'Backend restarted while this simulation was active. '
                'The previous worker process is no longer attached; restart the simulation.'
            )
            run_state.update({
                'runner_status': 'failed',
                'twitter_running': False,
                'reddit_running': False,
                'process_pid': None,
                'error': message,
                'updated_at': now,
                'completed_at': now,
            })
            with open(run_state_path, 'w', encoding='utf-8') as handle:
                json.dump(run_state, handle, ensure_ascii=False, indent=2)

            state_path = os.path.join(sim_dir, 'state.json')
            if os.path.isfile(state_path):
                with open(state_path, 'r', encoding='utf-8') as handle:
                    state = json.load(handle)
                state.update({'status': 'failed', 'error': message, 'updated_at': now})
                with open(state_path, 'w', encoding='utf-8') as handle:
                    json.dump(state, handle, ensure_ascii=False, indent=2)

            recovered += 1
        except Exception as exc:
            logger.warning('Failed to recover stale simulation %s: %s', simulation_id, exc)

    return recovered


def create_app(config_class=Config):
    """Create the JevFish Flask application."""
    frontend_dist = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../../frontend/dist')
    )
    has_frontend = os.path.isfile(os.path.join(frontend_dist, 'index.html'))

    app = Flask(
        __name__,
        static_folder=frontend_dist if has_frontend else None,
        static_url_path='' if has_frontend else None,
    )
    app.config.from_object(config_class)

    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    logger = setup_logger('jevfish')

    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info('=' * 50)
        logger.info('JevFish Backend starting...')
        logger.info('=' * 50)

    if Config.CORS_ALLOWED_ORIGINS:
        CORS(
            app,
            resources={r'/api/*': {'origins': Config.CORS_ALLOWED_ORIGINS}},
            supports_credentials=False,
        )

    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    recovered = _recover_interrupted_simulations(logger)
    if should_log_startup and recovered:
        logger.warning('Recovered %s interrupted simulation(s)', recovered)

    @app.before_request
    def protect_demo_mutations():
        request_logger = get_logger('jevfish.request')
        request_logger.debug('request: %s %s', request.method, request.path)

        if not Config.IS_PRODUCTION or request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return None

        expensive_start = request.path in {
            '/api/simulation/start',
            '/api/simulation/prepare',
        }
        protected_mutation = expensive_start or request.path.startswith('/api/graph/')
        if not protected_mutation:
            return None

        limit = (
            Config.DEMO_STARTS_PER_MINUTE
            if expensive_start
            else Config.DEMO_MUTATIONS_PER_MINUTE
        )
        if not _check_rate_limit(limit):
            return jsonify({
                'success': False,
                'error': 'Demo rate limit reached. Please retry in a minute.',
            }), 429

        if request.path == '/api/simulation/start':
            active = sum(
                1 for process in SimulationRunner._processes.values()
                if process is not None and process.poll() is None
            )
            if active >= Config.MAX_CONCURRENT_SIMULATIONS:
                return jsonify({
                    'success': False,
                    'error': (
                        'The public demo is at simulation capacity. '
                        'Please retry after an active run finishes.'
                    ),
                }), 429

        return None

    @app.after_request
    def harden_response(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        return response

    from .api import graph_bp, report_bp, simulation_bp, system_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(system_bp, url_prefix='/api/system')

    @app.route('/health')
    @app.route('/healthz')
    def health():
        return {'status': 'ok', 'service': 'JevFish'}

    @app.route('/readyz')
    def readiness():
        credential_checks = {
            'llm': bool(Config.LLM_API_KEY),
            'zep': bool(Config.ZEP_API_KEY),
            'typesafe': (
                bool(Config.TYPESAFE_API_KEY)
                if Config.JEVFISH_DECISION_ENGINE in {'hybrid', 'jev'}
                else True
            ),
        }
        storage_ok = False
        try:
            os.makedirs(Config.OASIS_SIMULATION_DATA_DIR, exist_ok=True)
            probe = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, '.ready-probe')
            with open(probe, 'w', encoding='utf-8') as handle:
                handle.write('ok')
            os.remove(probe)
            storage_ok = True
        except OSError:
            storage_ok = False

        ready = all(credential_checks.values()) and storage_ok
        return jsonify({
            'status': 'ready' if ready else 'not_ready',
            'service': 'JevFish',
            'checks': {**credential_checks, 'storage': storage_ok},
        }), 200 if ready else 503

    if has_frontend:
        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def serve_frontend(path: str):
            if path.startswith('api/') or path in {'health', 'healthz', 'readyz'}:
                abort(404)
            candidate = os.path.join(frontend_dist, path)
            if path and os.path.isfile(candidate):
                return send_from_directory(frontend_dist, path)
            return send_from_directory(frontend_dist, 'index.html')

    if should_log_startup:
        logger.info(
            'JevFish Backend ready (env=%s, frontend=%s, max_simulations=%s)',
            Config.APP_ENV,
            'bundled' if has_frontend else 'external/dev',
            Config.MAX_CONCURRENT_SIMULATIONS,
        )

    return app
