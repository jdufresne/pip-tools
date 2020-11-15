from __future__ import print_function

import locale

from .colorama import colorama

# Needed for locale.getpreferredencoding(False) to work
# in pip._internal.utils.encoding.auto_decode
try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error as e:  # pragma: no cover
    # setlocale can apparently crash if locale are uninitialized
    print("{}Ignoring error when setting locale: {}".format(colorama.Fore.RED, e))
