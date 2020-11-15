import sys

import mock
import pytest

from piptools.scripts import sync

from .utils import invoke


def test_run_as_module_sync():
    """piptools can be run as ``python -m piptools ...``."""

    status, out, err = invoke([sys.executable, "-m", "piptools", "sync", "--help"])

    # Should have run pip-compile successfully.
    assert status == 0
    assert out.startswith(b"usage:")
    assert b"Synchronize virtual environment with" in out
    assert err == b""


@mock.patch("piptools.sync.check_call")
def test_quiet_option(check_call, runner):
    """sync command can be run with `--quiet` or `-q` flag."""

    with open("requirements.txt", "w") as req_in:
        req_in.write("six==1.10.0")

    out = runner.invoke(sync, ["-q"])
    assert out.exit_code == 0
    assert out.stdout == ""
    assert out.stderr == ""

    # for every call to pip ensure the `-q` flag is set
    assert check_call.call_count == 2
    for call in check_call.call_args_list:
        assert "-q" in call[0][0]


@mock.patch("piptools.sync.check_call")
def test_quiet_option_when_up_to_date(check_call, runner):
    """
    Sync should output nothing when everything is up to date and quiet option is set.
    """
    with open("requirements.txt", "w"):
        pass

    with mock.patch("piptools.sync.diff", return_value=(set(), set())):
        out = runner.invoke(sync, ["-q"])

    assert out.exit_code == 0
    assert out.stdout == ""
    assert out.stderr == ""
    check_call.assert_not_called()


def test_no_requirements_file(runner):
    """
    It should raise an error if there are no input files
    or a requirements.txt file does not exist.
    """
    out = runner.invoke(sync)

    assert out.exit_code == 2
    assert out.stdout == ""
    assert "No requirement files given" in out.stderr


def test_input_files_with_dot_in_extension(runner):
    """
    It should raise an error if some of the input files have .in extension.
    """
    with open("requirements.in", "w") as req_in:
        req_in.write("six==1.10.0")

    out = runner.invoke(sync, ["requirements.in"])

    assert out.exit_code == 2
    assert out.stdout == ""
    assert "ERROR: Some input files have the .in extension" in out.stderr


def test_force_files_with_dot_in_extension(runner):
    """
    It should print a warning and sync anyway if some of the input files
    have .in extension.
    """

    with open("requirements.in", "w") as req_in:
        req_in.write("six==1.10.0")

    with mock.patch("piptools.sync.check_call"):
        out = runner.invoke(sync, ["requirements.in", "--force"])

    assert out.exit_code == 0
    assert out.stdout == ""
    assert "WARNING: Some input files have the .in extension" in out.stderr


@pytest.mark.parametrize(
    ("req_lines", "should_raise"),
    (
        (["six>1.10.0", "six<1.10.0"], True),
        (
            ["six>1.10.0 ; python_version>='3.0'", "six<1.10.0 ; python_version<'3.0'"],
            False,
        ),
    ),
)
def test_merge_error(req_lines, should_raise, runner):
    """
    Sync command should raise an error if there are merge errors.
    It should not raise an error if otherwise incompatible requirements
    are isolated by exclusive environment markers.
    """
    with open("requirements.txt", "w") as req_in:
        for line in req_lines:
            req_in.write(line + "\n")

    with mock.patch("piptools.sync.check_call"):
        out = runner.invoke(sync, ["-n"])

    if should_raise:
        assert out.exit_code == 2
        assert out.stdout == ""
        assert "Incompatible requirements found" in out.stderr
    else:
        assert out.exit_code == 1
        assert "Would uninstall:" in out.stdout
        assert out.stderr == ""


@pytest.mark.parametrize(
    ("cli_flags", "expected_install_flags"),
    (
        (
            ["--find-links", "./libs1", "--find-links", "./libs2"],
            ["--find-links", "./libs1", "--find-links", "./libs2"],
        ),
        (["--no-index"], ["--no-index"]),
        (
            ["--index-url", "https://example.com"],
            ["--index-url", "https://example.com"],
        ),
        (
            ["--extra-index-url", "https://foo", "--extra-index-url", "https://bar"],
            ["--extra-index-url", "https://foo", "--extra-index-url", "https://bar"],
        ),
        (
            ["--trusted-host", "foo", "--trusted-host", "bar"],
            ["--trusted-host", "foo", "--trusted-host", "bar"],
        ),
        (["--user"], ["--user"]),
        (["--cert", "foo.crt"], ["--cert", "foo.crt"]),
        (["--client-cert", "foo.pem"], ["--client-cert", "foo.pem"]),
        (
            ["--pip-args=--no-cache-dir --no-deps --no-warn-script-location"],
            ["--no-cache-dir", "--no-deps", "--no-warn-script-location"],
        ),
        (["--pip-args='--cache-dir=/tmp'"], ["--cache-dir=/tmp"]),
        (
            ["--pip-args=\"--cache-dir='/tmp/cache dir with spaces/'\""],
            ["--cache-dir='/tmp/cache dir with spaces/'"],
        ),
    ),
)
@mock.patch("piptools.sync.check_call")
def test_pip_install_flags(check_call, cli_flags, expected_install_flags, runner):
    """
    Test the cli flags have to be passed to the pip install command.
    """
    with open("requirements.txt", "w") as req_in:
        req_in.write("six==1.10.0")

    out = runner.invoke(sync, cli_flags)

    assert out.exit_code == 0
    assert out.stdout == ""
    assert out.stderr == ""

    call_args = [call[0][0] for call in check_call.call_args_list]
    called_install_options = [args[6:] for args in call_args if args[3] == "install"]
    assert called_install_options == [expected_install_flags], "Called args: {}".format(
        call_args
    )


@pytest.mark.parametrize(
    "install_flags",
    (
        ["--no-index"],
        ["--index-url", "https://example.com"],
        ["--extra-index-url", "https://example.com"],
        ["--find-links", "./libs1"],
        ["--trusted-host", "example.com"],
        ["--no-binary", ":all:"],
        ["--only-binary", ":all:"],
    ),
)
@mock.patch("piptools.sync.check_call")
def test_pip_install_flags_in_requirements_file(check_call, runner, install_flags):
    """
    Test the options from requirements.txt file pass to the pip install command.
    """
    with open(sync.DEFAULT_REQUIREMENTS_FILE, "w") as reqs:
        reqs.write(" ".join(install_flags) + "\n")
        reqs.write("six==1.10.0")

    out = runner.invoke(sync)

    assert out.exit_code == 0
    assert out.stdout == ""
    assert out.stderr == ""

    # Make sure pip install command has expected options
    call_args = [call[0][0] for call in check_call.call_args_list]
    called_install_options = [args[6:] for args in call_args if args[3] == "install"]
    assert called_install_options == [install_flags], "Called args: {}".format(
        call_args
    )


@mock.patch("piptools.sync.check_call")
def test_sync_ask_declined(check_call, runner):
    """
    Make sure nothing is installed if the confirmation is declined
    """
    with open("requirements.txt", "w") as req_in:
        req_in.write("small-fake-a==1.10.0")

    out = runner.invoke(sync, ["--ask"], input="n\n")

    assert out.exit_code == 1
    assert "Would uninstall:" in out.stdout
    assert out.stderr == ""

    check_call.assert_not_called()


@mock.patch("piptools.sync.check_call")
def test_sync_ask_accepted(check_call, runner):
    """
    Make sure pip is called when the confirmation is accepted (even if
    --dry-run is given)
    """
    with open("requirements.txt", "w") as req_in:
        req_in.write("small-fake-a==1.10.0")

    out = runner.invoke(sync, ["--ask", "--dry-run"], input="y\n")

    assert out.exit_code == 0
    assert "Would uninstall:" in out.stdout
    assert out.stderr == ""
    assert check_call.call_count == 2


def test_sync_dry_run_returns_non_zero_exit_code(runner):
    """
    Make sure non-zero exit code is returned when --dry-run is given.
    """
    with open("requirements.txt", "w") as req_in:
        req_in.write("small-fake-a==1.10.0")

    out = runner.invoke(sync, ["--dry-run"])

    assert out.exit_code == 1
    assert "Would uninstall:" in out.stdout
    assert out.stderr == ""
