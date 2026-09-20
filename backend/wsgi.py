"""Production WSGI entrypoint for JevFish."""

from app import create_app
from app.config import Config


errors = Config.validate()
if errors:
    formatted = '\n'.join(f'- {error}' for error in errors)
    raise RuntimeError(f'JevFish configuration is invalid:\n{formatted}')

app = create_app()
