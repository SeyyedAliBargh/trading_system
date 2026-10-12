import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv


def setup_logging(console_only=False):
    load_dotenv()
    root = logging.getLogger()
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    existing_project_handlers = [h for h in root.handlers if getattr(h, "_project_logging", False)]
    if existing_project_handlers:
        current_console_only = getattr(root, "_project_console_only", None)
        if current_console_only == console_only:
            root.setLevel(level)
            return level_name

    for handler in root.handlers[:]:
        if getattr(handler, "_project_logging", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    formatter.converter = time.gmtime

    console = logging.StreamHandler(sys.stdout)
    console._project_logging = True
    handlers = [console]

    if not console_only:
        log_dir = Path(os.getenv("LOG_DIR", "logs").strip())
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            max_mb = float(os.getenv("LOG_MAX_MB", "5").strip())
        except (ValueError, TypeError):
            max_mb = 5.0
        max_bytes = int(max_mb * 1024 * 1024)
        try:
            backups = int(os.getenv("LOG_BACKUPS", "10").strip())
        except (ValueError, TypeError):
            backups = 10

        app_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=max_bytes,
            backupCount=backups,
            encoding="utf-8",
        )
        app_handler._project_logging = True

        err_handler = RotatingFileHandler(
            log_dir / "errors.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        err_handler.setLevel(logging.WARNING)
        err_handler._project_logging = True

        handlers.extend([app_handler, err_handler])

    root.setLevel(level)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)

    root._project_console_only = console_only

    for name in ("httpx", "urllib3", "openai", "ccxt", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("uncaught").critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_exception
    return level_name
