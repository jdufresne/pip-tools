from __future__ import print_function

import os
from shutil import rmtree

from pip._internal.utils.appdirs import user_cache_dir

from .colorama import colorama

# The user_cache_dir helper comes straight from pip itself
CACHE_DIR = user_cache_dir("pip-tools")

# NOTE
# We used to store the cache dir under ~/.pip-tools, which is not the
# preferred place to store caches for any platform.  This has been addressed
# in pip-tools==1.0.5, but to be good citizens, we point this out explicitly
# to the user when this directory is still found.
LEGACY_CACHE_DIR = os.path.expanduser("~/.pip-tools")

if os.path.exists(LEGACY_CACHE_DIR):
    print(
        "{}Removing old cache dir {} (new cache dir is {})".format(
            colorama.Fore.YELLOW, LEGACY_CACHE_DIR, CACHE_DIR
        )
    )
    rmtree(LEGACY_CACHE_DIR)
