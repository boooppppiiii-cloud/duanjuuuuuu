import logging
from logging.handlers import RotatingFileHandler

from .config import get_settings


def configure_logging() -> None:
    log_dir = get_settings().log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        return
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)

