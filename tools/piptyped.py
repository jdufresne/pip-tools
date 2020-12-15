# Workaround https://github.com/pypa/pip/pull/9279
import site
from pathlib import Path

for directory in site.getsitepackages():
    typed = Path(directory, "pip", "py.typed")
    try:
        typed.touch()
    except FileNotFoundError:
        # Directory does not exist.
        pass
    else:
        break
