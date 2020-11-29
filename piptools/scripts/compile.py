# coding: utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import os
import shlex
import sys
import tempfile

from pip._internal.commands import create_command
from pip._internal.req.constructors import install_req_from_line
from pip._internal.utils.misc import redact_auth_from_url

from .._compat import parse_requirements
from ..cache import DependencyCache
from ..exceptions import PipToolsError
from ..locations import CACHE_DIR
from ..logging import log
from ..repositories import LocalRequirementsRepository, PyPIRepository
from ..resolver import Resolver
from ..utils import UNSAFE_PACKAGES, dedup, is_pinned_requirement, key_from_ireq
from ..writer import OutputWriter

DEFAULT_REQUIREMENTS_FILE = "requirements.in"
DEFAULT_REQUIREMENTS_OUTPUT_FILE = "requirements.txt"

# TODO: DIFF HELP AFTER DONE.
# TODO: RUN ON MY PROJECT AND COMPARE DIFFERENCES.
# TODO: ADD A TEST TO SNAPSHOT THE HELP SCREEN AS EARLY COMMIT.


def _get_default_option(option_name):
    """
    Get default value of the pip's option (including option from pip.conf)
    by a given option name.
    """
    install_command = create_command("install")
    default_values = install_command.parser.get_default_values()
    return getattr(default_values, option_name)


def add_args(parser):
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="Show more output"
    )
    parser.add_argument(
        "-q", "--quiet", action="count", default=0, help="Give less output"
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Only show what would happen, don't change anything",
    )
    parser.add_argument(
        "-p",
        "--pre",
        action="store_true",
        help="Allow resolving to prereleases (default is not)",
    )
    parser.add_argument(
        "-r",
        "--rebuild",
        action="store_true",
        help="Clear any caches upfront, rebuild from scratch",
    )
    parser.add_argument(
        "-f",
        "--find-links",
        action="append",
        default=[],
        help="Look for archives in this directory or on this HTML page",
    )
    parser.add_argument(
        "-i",
        "--index-url",
        help="Change index URL (defaults to {index_url})".format(
            index_url=redact_auth_from_url(_get_default_option("index_url"))
        ),
    )
    parser.add_argument(
        "--extra-index-url",
        action="append",
        default=[],
        help="Add additional index URL to search",
    )
    parser.add_argument("--cert", help="Path to alternate CA bundle.")
    parser.add_argument(
        "--client-cert",
        help="Path to SSL client certificate, a single file containing "
        "the private key and the certificate in PEM format.",
    )
    parser.add_argument(
        "--trusted-host",
        action="append",
        default=[],
        help="Mark this host as trusted, even though it does not have "
        "valid or any HTTPS.",
    )
    parser.add_argument(
        "--header",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add header to generated file",
    )
    parser.add_argument(
        "--emit-trusted-host",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add trusted host option to generated file",
    )
    parser.add_argument(
        "--annotate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Annotate results, indicating where dependencies come from",
    )
    parser.add_argument(
        "-U",
        "--upgrade",
        action="store_true",
        help="Try to upgrade all dependencies to their latest versions",
    )
    parser.add_argument(
        "-P",
        "--upgrade-package",
        dest="upgrade_packages",
        action="append",
        default=[],
        help="Specify particular packages to upgrade.",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        help=(
            "Output file name. Required if more than one input file is given. "
            "Will be derived from input file otherwise."
        ),
    )
    parser.add_argument(
        "--allow-unsafe",
        action="store_true",
        help="Pin packages considered unsafe: {}".format(
            ", ".join(sorted(UNSAFE_PACKAGES))
        ),
    )
    parser.add_argument(
        "--generate-hashes",
        action="store_true",
        help="Generate pip 8 style hashes in the resulting requirements file.",
    )
    parser.add_argument(
        "--reuse-hashes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Improve the speed of --generate-hashes by reusing the hashes from an "
            "existing output file."
        ),
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=10,
        help="Maximum number of rounds before resolving the requirements aborts.",
    )
    parser.add_argument(
        "--build-isolation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable isolation when building a modern source distribution. "
        "Build dependencies specified by PEP 518 must be already installed "
        "if build isolation is disabled.",
    )
    parser.add_argument(
        "--emit-find-links",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add the find-links option to generated file",
    )
    parser.add_argument(
        "--cache-dir", default=CACHE_DIR, help="Store the cache data in DIRECTORY."
    )
    parser.add_argument(
        "--pip-args", default="", help="Arguments to pass directly to the pip command."
    )
    parser.add_argument(
        "--emit-index-url",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add index URL to generated file",
    )
    parser.add_argument("src_files", nargs="*")


def cli(args):
    """Compiles requirements.txt from requirements.in specs."""
    log.verbosity = args.verbose - args.quiet

    src_files = args.src_files
    if len(src_files) == 0:
        if os.path.exists(DEFAULT_REQUIREMENTS_FILE):
            src_files = [DEFAULT_REQUIREMENTS_FILE]
        elif os.path.exists("setup.py"):
            src_files = ["setup.py"]
        else:
            raise click.BadParameter(
                (
                    "If you do not specify an input file, "
                    "the default is {} or setup.py"
                ).format(DEFAULT_REQUIREMENTS_FILE)
            )

    output_file = args.output_file
    if not output_file:
        if len(src_files) == 1:
            src_file = src_files[0]
            if src_file == "-":
                # An output file must be provided for stdin
                log.error(
                    "Error: --output-file is required if input is from stdin"
                )
            elif src_file == "setup.py":
                # Use default requirements output file if there is a setup.py
                # the source file.
                output_file = DEFAULT_REQUIREMENTS_OUTPUT_FILE
            else:
                # Otherwise derive the output file from the source file.
                base_name = src_files[0].rsplit(".", 1)[0]
                output_file = base_name + ".txt"
        else:
            # An output file must be provided if there are multiple source
            # files.
            raise click.BadParameter(
                "--output-file is required if two or more input files are given."
            )

    ###
    # Setup
    ###

    right_args = shlex.split(args.pip_args)
    pip_args = []
    for link in args.find_links:
        pip_args.extend(["-f", link])
    if args.index_url:
        pip_args.extend(["-i", args.index_url])
    for extra_index in args.extra_index_url:
        pip_args.extend(["--extra-index-url", extra_index])
    if args.cert:
        pip_args.extend(["--cert", args.cert])
    if args.client_cert:
        pip_args.extend(["--client-cert", args.client_cert])
    if args.pre:
        pip_args.extend(["--pre"])
    for host in args.trusted_host:
        pip_args.extend(["--trusted-host", host])

    if not args.build_isolation:
        pip_args.append("--no-build-isolation")
    pip_args.extend(right_args)

    repository = PyPIRepository(pip_args, cache_dir=args.cache_dir)

    # Parse all constraints coming from --upgrade-package/-P
    upgrade_reqs_gen = (install_req_from_line(pkg) for pkg in args.upgrade_packages)
    upgrade_install_reqs = {
        key_from_ireq(install_req): install_req for install_req in upgrade_reqs_gen
    }

    existing_pins_to_upgrade = set()

    # Proxy with a LocalRequirementsRepository if --upgrade is not specified
    # (= default invocation)
    if not args.upgrade and output_file and os.path.exists(output_file):
        # Use a temporary repository to ensure outdated(removed) options from
        # existing requirements.txt wouldn't get into the current repository.
        tmp_repository = PyPIRepository(pip_args, cache_dir=args.cache_dir)
        ireqs = parse_requirements(
            output_file,
            finder=tmp_repository.finder,
            session=tmp_repository.session,
            options=tmp_repository.options,
        )

        # Exclude packages from --upgrade-package/-P from the existing
        # constraints, and separately gather pins to be upgraded
        existing_pins = {}
        for ireq in filter(is_pinned_requirement, ireqs):
            key = key_from_ireq(ireq)
            if key in upgrade_install_reqs:
                existing_pins_to_upgrade.add(key)
            else:
                existing_pins[key] = ireq
        repository = LocalRequirementsRepository(
            existing_pins, repository, reuse_hashes=args.reuse_hashes
        )

    ###
    # Parsing/collecting initial requirements
    ###

    constraints = []
    for src_file in src_files:
        is_setup_file = os.path.basename(src_file) == "setup.py"
        if is_setup_file or src_file == "-":
            # pip requires filenames and not files. Since we want to support
            # piping from stdin, we need to briefly save the input from stdin
            # to a temporary file and have pip read that.  also used for
            # reading requirements from install_requires in setup.py.
            tmpfile = tempfile.NamedTemporaryFile(mode="wt", delete=False)
            if is_setup_file:
                from distutils.core import run_setup

                dist = run_setup(src_file)
                tmpfile.write("\n".join(dist.install_requires))
                comes_from = "{name} ({filename})".format(
                    name=dist.get_name(), filename=src_file
                )
            else:
                tmpfile.write(sys.stdin.read())
                comes_from = "-r -"
            tmpfile.flush()
            reqs = list(
                parse_requirements(
                    tmpfile.name,
                    finder=repository.finder,
                    session=repository.session,
                    options=repository.options,
                )
            )
            for req in reqs:
                req.comes_from = comes_from
            constraints.extend(reqs)
        else:
            constraints.extend(
                parse_requirements(
                    src_file,
                    finder=repository.finder,
                    session=repository.session,
                    options=repository.options,
                )
            )

    primary_packages = {
        key_from_ireq(ireq) for ireq in constraints if not ireq.constraint
    }

    allowed_upgrades = primary_packages | existing_pins_to_upgrade
    constraints.extend(
        ireq for key, ireq in upgrade_install_reqs.items() if key in allowed_upgrades
    )

    # Filter out pip environment markers which do not match (PEP496)
    constraints = [
        req for req in constraints if req.markers is None or req.markers.evaluate()
    ]

    log.debug("Using indexes:")
    with log.indentation():
        for index_url in dedup(repository.finder.index_urls):
            log.debug(redact_auth_from_url(index_url))

    if repository.finder.find_links:
        log.debug("")
        log.debug("Using links:")
        with log.indentation():
            for find_link in dedup(repository.finder.find_links):
                log.debug(redact_auth_from_url(find_link))

    try:
        resolver = Resolver(
            constraints,
            repository,
            prereleases=repository.finder.allow_all_prereleases or args.pre,
            cache=DependencyCache(args.cache_dir),
            clear_caches=args.rebuild,
            allow_unsafe=args.allow_unsafe,
        )
        results = resolver.resolve(max_rounds=args.max_rounds)
        if args.generate_hashes:
            hashes = resolver.resolve_hashes(results)
        else:
            hashes = None
    except PipToolsError as e:
        log.error(str(e))
        sys.exit(2)

    log.debug("")

    ##
    # Output
    ##

    with open(output_file, "w+b") as fp:
        writer = OutputWriter(
            src_files,
            fp,
            cli_args=args,
            dry_run=args.dry_run,
            emit_header=args.header,
            emit_index_url=args.emit_index_url,
            emit_trusted_host=args.emit_trusted_host,
            annotate=args.annotate,
            generate_hashes=args.generate_hashes,
            default_index_url=repository.DEFAULT_INDEX_URL,
            index_urls=repository.finder.index_urls,
            trusted_hosts=repository.finder.trusted_hosts,
            format_control=repository.finder.format_control,
            allow_unsafe=args.allow_unsafe,
            find_links=repository.finder.find_links,
            emit_find_links=args.emit_find_links,
        )
        writer.write(
            results=results,
            unsafe_requirements=resolver.unsafe_constraints,
            markers={
                key_from_ireq(ireq): ireq.markers
                for ireq in constraints
                if ireq.markers
            },
            hashes=hashes,
        )

    if args.dry_run:
        log.info("Dry-run, so nothing updated.")
