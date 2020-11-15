import os
import subprocess


def invoke(command):
    """Invoke sub-process."""
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return p.returncode, out, err


# NOTE: keep in sync with "passenv" in tox.ini
CI_VARIABLES = {"CI", "GITHUB_ACTIONS"}


def looks_like_ci():
    return bool(set(os.environ.keys()) & CI_VARIABLES)
