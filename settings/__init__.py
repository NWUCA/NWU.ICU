import os
from pathlib import Path


def ensure_log_directory():
    base_dir = Path(__file__).resolve().parent.parent
    log_dir = base_dir / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / 'NWUICU.log'

    if not log_file.exists():
        log_file.touch()

    if not os.access(log_dir, os.W_OK):
        print(f"Warning: No write access to log directory: {log_dir}")
    if not os.access(log_file, os.W_OK):
        print(f"Warning: No write access to log file: {log_file}")


ensure_log_directory()
