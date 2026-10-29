"""Read an explicit local configuration file without executing its contents."""
import os
from pathlib import Path

VARIABLES = {'MODEL_API_KEY', 'MODEL_BASE_URL', 'MODEL_NAME', 'MODEL_ALLOW_HTTP'}


def load_env_file(path='.env'):
    """Process environment wins; missing default file is fine. Never log values."""
    source = Path(path)
    if not source.exists():
        if source == Path('.env'):
            return
        raise ValueError('specified model configuration file does not exist')
    values = {}
    for number, line in enumerate(source.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if not separator or name not in VARIABLES:
            raise ValueError(f'invalid model configuration entry on line {number}; expected a supported MODEL_ variable')
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'unclosed configuration quote on line {number}')
            value = value[1:-1]
        values[name] = value
    for name, value in values.items():
        os.environ.setdefault(name, value)
