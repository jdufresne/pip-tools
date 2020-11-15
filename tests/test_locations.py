import os
import sys

from .utils import invoke


def test_remove_legacy_cache_dir():
    """
    Check that legacy cache dir is removed at import time.
    """
    os.mkdir(os.path.expanduser("~/.pip-tools"))

    status, out, err = invoke([sys.executable, "-m", "piptools"])

    assert status == 0
    assert out.startswith(b"Removing old cache dir")
    assert err == b""
