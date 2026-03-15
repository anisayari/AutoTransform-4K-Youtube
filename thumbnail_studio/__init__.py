from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from flask import Flask
from dotenv import load_dotenv

from .config import AppConfig, resolve_env_file
from .routes import bp


def configure_logging(settings: AppConfig) -> None:
    package_logger = logging.getLogger("thumbnail_studio")
    package_logger.setLevel(logging.INFO)

    log_path = settings.app_log_file.resolve()
    for handler in package_logger.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == str(log_path):
            return

    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
    )
    package_logger.addHandler(handler)
    package_logger.propagate = False
    package_logger.info("Logging initialized at %s", log_path)


def create_app() -> Flask:
    load_dotenv(dotenv_path=resolve_env_file())
    settings = AppConfig.from_env()
    settings.ensure_directories()
    configure_logging(settings)

    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = settings.secret_key
    app.config["APP_SETTINGS"] = settings
    app.config["JSON_SORT_KEYS"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    app.register_blueprint(bp)
    return app
