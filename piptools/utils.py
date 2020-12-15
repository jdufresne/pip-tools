import shlex
from collections import OrderedDict
from itertools import chain
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from click.utils import LazyFile
from pip._internal.req import InstallRequirement
from pip._internal.req.constructors import install_req_from_line
from pip._internal.utils.misc import redact_auth_from_url
from pip._internal.vcs import is_url
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.pkg_resources import Distribution

from .click import style

_T = TypeVar("_T")

UNSAFE_PACKAGES = {"setuptools", "distribute", "pip"}
COMPILE_EXCLUDE_OPTIONS = {
    "--dry-run",
    "--quiet",
    "--rebuild",
    "--upgrade",
    "--upgrade-package",
    "--verbose",
    "--cache-dir",
    "--no-reuse-hashes",
}


def key_from_ireq(ireq: InstallRequirement) -> str:
    """Get a standardized key for an InstallRequirement."""
    if ireq.req is None and ireq.link is not None:
        return str(ireq.link)
    assert ireq.req is not None
    return key_from_req(ireq.req)


def key_from_req(req: Union[Distribution, Requirement]) -> str:
    """Get an all-lowercase version of the requirement's name."""
    key: str
    if isinstance(req, Distribution):
        # from pkg_resources, such as installed dists for pip-sync
        key = req.key
    else:
        # from packaging, such as install requirements from requirements.txt
        key = req.name

    key = key.replace("_", "-").lower()
    return key


def comment(text: str) -> str:
    return style(text, fg="green")


def make_install_requirement(
    name: str, version: str, extras: Iterable[str], constraint: bool = False
) -> InstallRequirement:
    # If no extras are specified, the extras string is blank
    extras_string = ""
    if extras:
        # Sort extras for stability
        extras_string = f"[{','.join(sorted(extras))}]"

    return install_req_from_line(
        str(f"{name}{extras_string}=={version}"), constraint=constraint
    )


def is_url_requirement(ireq: InstallRequirement) -> bool:
    """
    Return True if requirement was specified as a path or URL.
    ireq.original_link will have been set by InstallRequirement.__init__
    """
    return bool(ireq.original_link)


def format_requirement(
    ireq: InstallRequirement,
    marker: Optional[str] = None,
    hashes: Optional[Iterable[str]] = None,
) -> str:
    """
    Generic formatter for pretty printing InstallRequirements to the terminal
    in a less verbose way than using its `__str__` method.
    """
    if ireq.editable:
        assert ireq.link is not None
        line = f"-e {ireq.link.url}"
    elif is_url_requirement(ireq):
        assert ireq.link is not None
        line = ireq.link.url
    else:
        line = str(ireq.req).lower()

    if marker:
        line = f"{line} ; {marker}"

    if hashes:
        for hash_ in sorted(hashes):
            line += f" \\\n    --hash={hash_}"

    return line


def format_specifier(ireq: InstallRequirement) -> str:
    """
    Generic formatter for pretty printing the specifier part of
    InstallRequirements to the terminal.
    """
    # TODO: Ideally, this is carried over to the pip library itself
    specs = ireq.specifier if ireq.req is not None else []
    specs = sorted(specs, key=lambda x: x.version)
    return ",".join(str(s) for s in specs) or "<any>"


def is_pinned_requirement(ireq: InstallRequirement) -> bool:
    """
    Returns whether an InstallRequirement is a "pinned" requirement.

    An InstallRequirement is considered pinned if:

    - Is not editable
    - It has exactly one specifier
    - That specifier is "=="
    - The version does not contain a wildcard

    Examples:
        django==1.8   # pinned
        django>1.8    # NOT pinned
        django~=1.8   # NOT pinned
        django==1.*   # NOT pinned
    """
    if ireq.editable:
        return False

    if ireq.req is None or len(ireq.specifier) != 1:
        return False

    spec = next(iter(ireq.specifier))
    return spec.operator in {"==", "==="} and not spec.version.endswith(".*")


def as_tuple(ireq: InstallRequirement) -> Tuple[str, str, Tuple[str, ...]]:
    """
    Pulls out the (name: str, version:str, extras:(str)) tuple from
    the pinned InstallRequirement.
    """
    if not is_pinned_requirement(ireq):
        raise TypeError(f"Expected a pinned InstallRequirement, got {ireq}")

    name = key_from_ireq(ireq)
    version = next(iter(ireq.specifier)).version
    extras = tuple(sorted(ireq.extras))
    return name, version, extras


def flat_map(fn: Callable, collection: Iterable) -> Iterator:
    """Map a function over a collection and flatten the result by one-level"""
    return chain.from_iterable(map(fn, collection))


# TODO: Use Literal?
def lookup_table(
    values: Iterable[str],
    key: Optional[Callable] = None,
    keyval: Optional[Callable] = None,
    unique: bool = False,
    use_lists: bool = False,
) -> Dict[str, Union[str, List[str]]]:
    """
    Builds a dict-based lookup table (index) elegantly.

    Supports building normal and unique lookup tables.  For example:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'], lambda s: s[0]) == {
    ...     'b': {'bar', 'baz'},
    ...     'f': {'foo'},
    ...     'q': {'quux', 'qux'}
    ... }

    For key functions that uniquely identify values, set unique=True:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'], lambda s: s[0],
    ...     unique=True) == {
    ...     'b': 'baz',
    ...     'f': 'foo',
    ...     'q': 'quux'
    ... }

    For the values represented as lists, set use_lists=True:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'], lambda s: s[0],
    ...     use_lists=True) == {
    ...     'b': ['bar', 'baz'],
    ...     'f': ['foo'],
    ...     'q': ['qux', 'quux']
    ... }

    The values of the resulting lookup table will be lists, not sets.

    For extra power, you can even change the values while building up the LUT.
    To do so, use the `keyval` function instead of the `key` arg:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'],
    ...     keyval=lambda s: (s[0], s[1:])) == {
    ...     'b': {'ar', 'az'},
    ...     'f': {'oo'},
    ...     'q': {'uux', 'ux'}
    ... }

    """
    if keyval is None:
        if key is None:

            def keyval(v):
                return v

        else:

            def keyval(v):
                return (key(v), v)

    if unique:
        return dict(keyval(v) for v in values)

    lut = {}
    for value in values:
        k, v = keyval(value)
        try:
            s = lut[k]
        except KeyError:
            if use_lists:
                s = lut[k] = list()
            else:
                s = lut[k] = set()
        if use_lists:
            s.append(v)
        else:
            s.add(v)
    return dict(lut)


def dedup(iterable: Iterable[_T]) -> Iterable[_T]:
    """Deduplicate an iterable object like iter(set(iterable)) but
    order-preserved.
    """
    return iter(OrderedDict.fromkeys(iterable))


def name_from_req(req: Union[Distribution, Requirement]) -> str:
    """Get the name of the requirement"""
    if isinstance(req, Distribution):
        # from pkg_resources, such as installed dists for pip-sync
        return req.project_name
    else:
        # from packaging, such as install requirements from requirements.txt
        return req.name


def get_hashes_from_ireq(ireq: InstallRequirement) -> List[str]:
    """
    Given an InstallRequirement, return a list of string hashes in
    the format "{algorithm}:{hash}". Return an empty list if there are no hashes
    in the requirement options.
    """
    result = []
    for algorithm, hexdigests in ireq.hash_options.items():
        for hash_ in hexdigests:
            result.append(f"{algorithm}:{hash_}")
    return result


def force_text(s: Any) -> str:
    """
    Return a string representing `s`.
    """
    if s is None:
        return ""
    if not isinstance(s, str):
        return str(s)
    return s


def get_compile_command(click_ctx):
    """
    Returns a normalized compile command depending on cli context.

    The command will be normalized by:
        - expanding options short to long
        - removing values that are already default
        - sorting the arguments
        - removing one-off arguments like '--upgrade'
        - removing arguments that don't change build behaviour like '--verbose'
    """
    from piptools.scripts.compile import cli

    # Map of the compile cli options (option name -> click.Option)
    compile_options = {option.name: option for option in cli.params}

    left_args = []
    right_args = []

    for option_name, value in click_ctx.params.items():
        option = compile_options[option_name]

        # Collect variadic args separately, they will be added
        # at the end of the command later
        if option.nargs < 0:
            # These will necessarily be src_files
            # Re-add click-stripped '--' if any start with '-'
            if any(val.startswith("-") and val != "-" for val in value):
                right_args.append("--")
            right_args.extend([shlex.quote(force_text(val)) for val in value])
            continue

        # Get the latest option name (usually it'll be a long name)
        option_long_name = option.opts[-1]

        # Exclude one-off options (--upgrade/--upgrade-package/--rebuild/...)
        # or options that don't change compile behaviour (--verbose/--dry-run/...)
        if option_long_name in COMPILE_EXCLUDE_OPTIONS:
            continue

        # Skip options without a value
        if option.default is None and not value:
            continue

        # Skip options with a default value
        if option.default == value:
            continue

        # Use a file name for file-like objects
        if isinstance(value, LazyFile):
            value = value.name

        # Convert value to the list
        if not isinstance(value, (tuple, list)):
            value = [value]

        for val in value:
            # Flags don't have a value, thus add to args true or false option long name
            if option.is_flag:
                # If there are false-options, choose an option name depending on a value
                if option.secondary_opts:
                    # Get the latest false-option
                    secondary_option_long_name = option.secondary_opts[-1]
                    arg = option_long_name if val else secondary_option_long_name
                # There are no false-options, use true-option
                else:
                    arg = option_long_name
                left_args.append(shlex.quote(arg))
            # Append to args the option with a value
            else:
                if isinstance(val, str) and is_url(val):
                    val = redact_auth_from_url(val)
                if option.name == "pip_args":
                    # shlex.quote() would produce functional but noisily quoted results,
                    # e.g. --pip-args='--cache-dir='"'"'/tmp/with spaces'"'"''
                    # Instead, we try to get more legible quoting via repr:
                    left_args.append(f"{option_long_name}={repr(val)}")
                else:
                    left_args.append(
                        f"{option_long_name}={shlex.quote(force_text(val))}"
                    )

    return " ".join(["pip-compile", *sorted(left_args), *sorted(right_args)])
