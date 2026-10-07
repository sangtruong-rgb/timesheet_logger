"""Explicit token paths: CLI > exported environment > profile > root defaults."""
import os
from pathlib import Path
from activity_settings import DEFAULT_CONFIG, load_config
ROOT = Path(__file__).resolve().parent.parent

def token_settings(config_path=None, claude_dir=None, csv_path=None):
    config = load_config(config_path); token = config.get('token_tracking', {})
    if not isinstance(token, dict): raise ValueError('token_tracking must be an object')
    base = Path(config_path).expanduser().resolve().parent if config_path else DEFAULT_CONFIG.parent
    def resolve(cli, environment, key, default):
        value = cli if cli is not None else os.environ.get(environment)
        relative = Path.cwd()
        if value is None:
            value = token.get(key); relative = base
        if value is None: return default
        if not isinstance(value, str) or not value.strip(): raise ValueError(f'{key} must be a nonempty path')
        path = Path(value).expanduser()
        return path if path.is_absolute() else relative/path
    return {'claude_dir': resolve(claude_dir, 'CLAUDE_DIR', 'claude_dir', Path.home()/'.claude'),
            'csv_path': resolve(csv_path, 'TIMESHEET_TOKEN_CSV', 'csv_path', ROOT/'data/token-usage.csv')}
