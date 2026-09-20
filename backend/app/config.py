"""
JevFish configuration.

Loads the repository-root .env for local development and falls back to process
environment variables in deployed environments.
"""

import os
from dotenv import load_dotenv


project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    load_dotenv(override=True)


def _csv_env(name: str, default: str = "") -> list[str]:
    return [value.strip() for value in os.environ.get(name, default).split(',') if value.strip()]


class Config:
    # Runtime environment
    APP_ENV = os.environ.get('APP_ENV', 'development').strip().lower()
    IS_PRODUCTION = APP_ENV == 'production'

    # Flask
    # Production deliberately has no fallback. Local development keeps a harmless
    # fallback so contributors can boot the app without extra ceremony.
    SECRET_KEY = os.environ.get('SECRET_KEY') or (
        'jevfish-dev-secret-key' if not IS_PRODUCTION else ''
    )
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    JSON_AS_ASCII = False

    # CORS is unnecessary for the recommended single-origin Docker deployment.
    # Set this explicitly only when the frontend is hosted on another origin.
    CORS_ALLOWED_ORIGINS = _csv_env(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:3000,http://localhost:5173' if not IS_PRODUCTION else '',
    )

    # Demo safety limits. The production demo intentionally runs as one web
    # worker because simulation state/process ownership is local to the instance.
    MAX_CONCURRENT_SIMULATIONS = int(os.environ.get('MAX_CONCURRENT_SIMULATIONS', '2'))
    DEMO_STARTS_PER_MINUTE = int(os.environ.get('DEMO_STARTS_PER_MINUTE', '4'))
    DEMO_MUTATIONS_PER_MINUTE = int(os.environ.get('DEMO_MUTATIONS_PER_MINUTE', '20'))

    # LLM configuration (OpenAI-compatible)
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # TypeSafe / Jev System One
    TYPESAFE_API_KEY = os.environ.get('TYPESAFE_API_KEY')
    TYPESAFE_DEFAULT_MODEL = os.environ.get('TYPESAFE_DEFAULT_MODEL', 'jev-latest')
    JEVFISH_DECISION_ENGINE = os.environ.get('JEVFISH_DECISION_ENGINE', 'hybrid').strip().lower()
    JEVFISH_OBSERVATION_MODE = os.environ.get('JEVFISH_OBSERVATION_MODE', 'oasis_refresh')

    # Zep
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')

    # Uploads
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # Text processing
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    # OASIS simulation
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report agent
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls) -> list[str]:
        errors: list[str] = []

        if not cls.LLM_API_KEY:
            errors.append('LLM_API_KEY is not configured')
        if not cls.ZEP_API_KEY:
            errors.append('ZEP_API_KEY is not configured')
        if cls.JEVFISH_DECISION_ENGINE in {'hybrid', 'jev'} and not cls.TYPESAFE_API_KEY:
            errors.append('TYPESAFE_API_KEY is not configured for the selected JevFish mode')
        if os.environ.get('ZEP_API_URL'):
            errors.append('ZEP_API_URL is unsupported; JevFish connects to Zep Cloud')

        if cls.IS_PRODUCTION:
            if len(cls.SECRET_KEY) < 32:
                errors.append('SECRET_KEY must be set to at least 32 characters in production')
            if cls.DEBUG:
                errors.append('FLASK_DEBUG must be false in production')
            if cls.MAX_CONCURRENT_SIMULATIONS < 1:
                errors.append('MAX_CONCURRENT_SIMULATIONS must be at least 1')
        elif cls.DEBUG:
            import warnings
            warnings.warn('Flask DEBUG mode is enabled. Do not use in production.', RuntimeWarning)

        return errors
