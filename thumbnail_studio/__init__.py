from __future__ import annotations

from flask import Flask
from dotenv import load_dotenv

from .config import AppConfig, resolve_env_file
from .routes import bp


def create_app() -> Flask:
    load_dotenv(dotenv_path=resolve_env_file())
    settings = AppConfig.from_env()
    settings.ensure_directories()

    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = settings.secret_key
    app.config["APP_SETTINGS"] = settings
    app.config["JSON_SORT_KEYS"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    app.register_blueprint(bp)
    return app
