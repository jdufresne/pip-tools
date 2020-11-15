# coding: utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

import contextlib
import logging
import re
import sys

from .colorama import colorama

# Initialise the builtin logging module for other component using it.
# Ex: pip
logging.basicConfig()

# TODO: CAN WE DO BETTER?
_ansi_re = re.compile(r"\033\[[;?0-9]*[a-zA-Z]")


def unstyle(value):
    return _ansi_re.sub("", value)


class LogContext(object):
    stream = sys.stderr

    def __init__(self, verbosity=0, indent_width=2):
        self.verbosity = verbosity
        self.current_indent = 0
        self._indent_width = indent_width

    def log(self, message):
        prefix = " " * self.current_indent
        if not sys.stderr.isatty():
            message = unstyle(message)
        print(prefix + message, file=sys.stderr)

    def debug(self, message):
        if self.verbosity >= 1:
            self.log(message)

    def info(self, message):
        if self.verbosity >= 0:
            self.log(message)

    def warning(self, message):
        self.log(colorama.Fore.YELLOW + message)

    def error(self, message):
        self.log(colorama.Fore.RED + message)

    def _indent(self):
        self.current_indent += self._indent_width

    def _dedent(self):
        self.current_indent -= self._indent_width

    @contextlib.contextmanager
    def indentation(self):
        """
        Increase indentation.
        """
        self._indent()
        try:
            yield
        finally:
            self._dedent()


log = LogContext()
