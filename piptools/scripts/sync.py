# coding: utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

import itertools
import os
import shlex
import sys

from pip._internal.commands import create_command
from pip._internal.utils.misc import get_installed_distributions

from .. import sync
from .._compat import parse_requirements
from ..exceptions import PipToolsError
from ..logging import log
from ..repositories import PyPIRepository
from ..utils import flat_map

DEFAULT_REQUIREMENTS_FILE = "requirements.txt"


def add_args(parser):
    # @click.command(context_settings={"help_option_names": ("-h", "--help")})
    # @click.version_option()
    parser.add_argument(
        "-a",
        "--ask",
        action="store_true",
        help="Show what would happen, then ask whether to continue",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Only show what would happen, don't change anything",
    )
    parser.add_argument(
        "--force", action="store_true", help="Proceed even if conflicts are found"
    )
    parser.add_argument(
        "-f",
        "--find-links",
        action="append",
        default=[],
        help="Look for archives in this directory or on this HTML page",
    )
    parser.add_argument(
        "-i", "--index-url", help="Change index URL (defaults to PyPI)",
    )
    parser.add_argument(
        "--extra-index-url",
        action="append",
        default=[],
        help="Add additional index URL to search",
    )
    parser.add_argument(
        "--trusted-host",
        action="append",
        default=[],
        help="Mark this host as trusted, even though it does not have valid or any HTTPS.",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Ignore package index (only looking at --find-links URLs instead)",
    )
    parser.add_argument(
        "-q", "--quiet", action="count", default=0, help="Give less output"
    )
    parser.add_argument(
        "--user",
        dest="user_only",
        action="store_true",
        help="Restrict attention to user directory",
    )
    parser.add_argument("--cert", help="Path to alternate CA bundle.")
    parser.add_argument(
        "--client-cert",
        help="Path to SSL client certificate, a single file containing "
        "the private key and the certificate in PEM format.",
    )
    parser.add_argument("src_files", nargs="*")
    parser.add_argument("--pip-args", help="Arguments to pass directly to pip install.")


def cli(args):
    """Synchronize virtual environment with requirements.txt."""
    log.verbosity = args.verbose - args.quiet

    src_files = args.src_files
    if not src_files:
        if os.path.exists(DEFAULT_REQUIREMENTS_FILE):
            src_files = (DEFAULT_REQUIREMENTS_FILE,)
        else:
            msg = "No requirement files given and no {} found in the current directory"
            log.error(msg.format(DEFAULT_REQUIREMENTS_FILE))
            sys.exit(2)

    if any(src_file.endswith(".in") for src_file in src_files):
        msg = (
            "Some input files have the .in extension, which is most likely an error "
            "and can cause weird behaviour. You probably meant to use "
            "the corresponding *.txt file?"
        )
        if args.force:
            log.warning("WARNING: " + msg)
        else:
            log.error("ERROR: " + msg)
            sys.exit(2)

    install_command = create_command("install")
    options, _ = install_command.parse_args([])
    session = install_command._build_session(options)
    finder = install_command._build_package_finder(options=options, session=session)

    # Parse requirements file. Note, all options inside requirements file
    # will be collected by the finder.
    requirements = flat_map(
        lambda src: parse_requirements(src, finder=finder, session=session), src_files
    )

    try:
        requirements = sync.merge(requirements, ignore_conflicts=args.force)
    except PipToolsError as e:
        log.error(str(e))
        sys.exit(2)

    installed_dists = get_installed_distributions(skip=[], user_only=args.user_only)
    to_install, to_uninstall = sync.diff(requirements, installed_dists)

    install_flags = _compose_install_flags(
        finder,
        no_index=args.no_index,
        index_url=args.index_url,
        extra_index_url=args.extra_index_url,
        trusted_host=args.trusted_host,
        find_links=args.find_links,
        user_only=args.user_only,
        cert=args.cert,
        client_cert=args.client_cert,
    ) + shlex.split(args.pip_args or "")
    sys.exit(
        sync.sync(
            to_install,
            to_uninstall,
            dry_run=args.dry_run,
            install_flags=install_flags,
            ask=args.ask,
        )
    )


def _compose_install_flags(
    finder,
    no_index=False,
    index_url=None,
    extra_index_url=None,
    trusted_host=None,
    find_links=None,
    user_only=False,
    cert=None,
    client_cert=None,
):
    """
    Compose install flags with the given finder and CLI options.
    """
    result = []

    # Build --index-url/--extra-index-url/--no-index
    if no_index:
        result.append("--no-index")
    elif index_url:
        result.extend(["--index-url", index_url])
    elif finder.index_urls:
        finder_index_url = finder.index_urls[0]
        if finder_index_url != PyPIRepository.DEFAULT_INDEX_URL:
            result.extend(["--index-url", finder_index_url])
        for extra_index in finder.index_urls[1:]:
            result.extend(["--extra-index-url", extra_index])
    else:
        result.append("--no-index")

    for extra_index in extra_index_url:
        result.extend(["--extra-index-url", extra_index])

    # Build --trusted-hosts
    for host in itertools.chain(trusted_host, finder.trusted_hosts):
        result.extend(["--trusted-host", host])

    # Build --find-links
    for link in itertools.chain(find_links, finder.find_links):
        result.extend(["--find-links", link])

    # Build format controls --no-binary/--only-binary
    for format_control in ("no_binary", "only_binary"):
        formats = getattr(finder.format_control, format_control)
        if not formats:
            continue
        result.extend(
            ["--" + format_control.replace("_", "-"), ",".join(sorted(formats))]
        )

    if user_only:
        result.append("--user")

    if cert:
        result.extend(["--cert", cert])

    if client_cert:
        result.extend(["--client-cert", client_cert])

    return result
