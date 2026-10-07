"""shared utilities — config, logger, dir setup, shell helper."""
import logging
import subprocess
import sys
from pathlib import Path
import yaml


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def setup_logger(level: str, log_file: str) -> logging.Logger:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("autocc")
    logger.setLevel(getattr(logging, level.upper()))
    if logger.handlers:
        return logger

    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s",
                            "%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_file)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


def ensure_dirs(paths: dict):
    for k, v in paths.items():
        Path(v).mkdir(parents=True, exist_ok=True)


def run(cmd: list, logger=None, capture=True, timeout=None):
    """run shell command, return (rc, stdout, stderr)."""
    if logger:
        logger.debug(f"exec: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError as e:
        if logger:
            logger.error(f"binary not found: {cmd[0]} — {e}")
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        if logger:
            logger.error(f"timeout: {cmd[0]}")
        return 124, "", "timeout"


def which(binary: str) -> bool:
    from shutil import which as _which
    return _which(binary) is not None
