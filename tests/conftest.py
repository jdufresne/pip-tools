import argparse
import io
import json
import os
import sys
from contextlib import contextmanager
from functools import partial
from subprocess import check_call
from textwrap import dedent

import pytest
from pip._internal.models.candidate import InstallationCandidate
from pip._internal.req.constructors import (
    install_req_from_editable,
    install_req_from_line,
)
from pip._vendor.packaging.version import Version
from pip._vendor.pkg_resources import Requirement

from piptools.cache import DependencyCache
from piptools.exceptions import NoCandidateFound
from piptools.repositories import PyPIRepository
from piptools.repositories.base import BaseRepository
from piptools.resolver import Resolver
from piptools.utils import (
    as_tuple,
    is_url_requirement,
    key_from_ireq,
    key_from_req,
    make_install_requirement,
)

from .constants import MINIMAL_WHEELS_PATH
from .utils import looks_like_ci


class FakeRepository(BaseRepository):
    def __init__(self):
        with open("tests/test_data/fake-index.json", "r") as f:
            self.index = json.load(f)

        with open("tests/test_data/fake-editables.json", "r") as f:
            self.editables = json.load(f)

    @contextmanager
    def freshen_build_caches(self):
        yield

    def get_hashes(self, ireq):
        # Some fake hashes
        return {
            "test:123",
            "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        }

    def find_best_match(self, ireq, prereleases=False):
        if ireq.editable:
            return ireq

        versions = list(
            ireq.specifier.filter(
                self.index[key_from_ireq(ireq)], prereleases=prereleases
            )
        )
        if not versions:
            tried_versions = [
                InstallationCandidate(ireq.name, version, "https://fake.url.foo")
                for version in self.index[key_from_ireq(ireq)]
            ]
            raise NoCandidateFound(ireq, tried_versions, ["https://fake.url.foo"])
        best_version = max(versions, key=Version)
        return make_install_requirement(
            key_from_ireq(ireq), best_version, ireq.extras, constraint=ireq.constraint
        )

    def get_dependencies(self, ireq):
        if ireq.editable or is_url_requirement(ireq):
            return self.editables[str(ireq.link)]

        name, version, extras = as_tuple(ireq)
        # Store non-extra dependencies under the empty string
        extras += ("",)
        dependencies = [
            dep for extra in extras for dep in self.index[name][version][extra]
        ]
        return [
            install_req_from_line(dep, constraint=ireq.constraint)
            for dep in dependencies
        ]

    @contextmanager
    def allow_all_wheels(self):
        # No need to do an actual pip.Wheel mock here.
        yield

    def copy_ireq_dependencies(self, source, dest):
        # No state to update.
        pass


class FakeInstalledDistribution(object):
    def __init__(self, line, deps=None):
        if deps is None:
            deps = []
        self.deps = [Requirement.parse(d) for d in deps]

        self.req = Requirement.parse(line)

        self.key = key_from_req(self.req)
        self.specifier = self.req.specifier

        self.version = line.split("==")[1]

    def requires(self):
        return self.deps


def pytest_collection_modifyitems(config, items):
    for item in items:
        # Mark network tests as flaky
        if item.get_closest_marker("network") and looks_like_ci():
            item.add_marker(pytest.mark.flaky(reruns=3, reruns_delay=2))


@pytest.fixture
def fake_dist():
    return FakeInstalledDistribution


@pytest.fixture
def repository():
    return FakeRepository()


@pytest.fixture
def pypi_repository(tmpdir):
    return PyPIRepository(
        ["--index-url", PyPIRepository.DEFAULT_INDEX_URL],
        cache_dir=str(tmpdir / "pypi-repo"),
    )


@pytest.fixture
def depcache(tmpdir):
    return DependencyCache(str(tmpdir / "dep-cache"))


@pytest.fixture
def resolver(depcache, repository):
    # TODO: It'd be nicer if Resolver instance could be set up and then
    #       use .resolve(...) on the specset, instead of passing it to
    #       the constructor like this (it's not reusable)
    return partial(Resolver, repository=repository, cache=depcache)


@pytest.fixture
def base_resolver(depcache):
    return partial(Resolver, cache=depcache)


@pytest.fixture
def from_line():
    return install_req_from_line


@pytest.fixture
def from_editable():
    return install_req_from_editable


# TODO: Don't use capsys, it interferes with debug printing.
class CliRunnerResult:
    def __init__(self, exit_code, capsys):
        self.exit_code = exit_code
        self.stdout, self.stderr = capsys.readouterr()


class CliRunner:
    def __init__(self, capsys, monkeypatch):
        self.capsys = capsys
        self.monkeypatch = monkeypatch

    def invoke(self, mod, args=None, input=None):
        parser = argparse.ArgumentParser(mod.__name__)
        mod.add_args(parser)
        if args is None:
            args = []
        args = parser.parse_args(args)
        with self.monkeypatch.context() as m:
            if input is not None:
                m.setattr("sys.stdin", io.StringIO(input))
            try:
                mod.cli(args)
            except SystemExit as e:
                exit_code = e.code
            else:
                exit_code = 0
        return CliRunnerResult(exit_code, self.capsys)


@pytest.fixture
def runner(tmpdir_cwd, capsys, monkeypatch):
    cli_runner = CliRunner(capsys, monkeypatch)
    return cli_runner


@pytest.fixture
def tmpdir_cwd(tmpdir):
    with tmpdir.as_cwd():
        yield tmpdir


@pytest.fixture
def make_pip_conf(tmpdir, monkeypatch):
    created_paths = []

    def _make_pip_conf(content):
        pip_conf_file = "pip.conf" if os.name != "nt" else "pip.ini"
        path = (tmpdir / pip_conf_file).strpath

        with open(path, "w") as f:
            f.write(content)

        monkeypatch.setenv("PIP_CONFIG_FILE", path)

        created_paths.append(path)
        return path

    try:
        yield _make_pip_conf
    finally:
        for path in created_paths:
            os.remove(path)


@pytest.fixture
def pip_conf(make_pip_conf):
    return make_pip_conf(
        dedent(
            """\
            [global]
            no-index = true
            find-links = {wheels_path}
            """.format(
                wheels_path=MINIMAL_WHEELS_PATH
            )
        )
    )


@pytest.fixture
def pip_with_index_conf(make_pip_conf):
    return make_pip_conf(
        dedent(
            """\
            [global]
            index-url = http://example.com
            find-links = {wheels_path}
            """.format(
                wheels_path=MINIMAL_WHEELS_PATH
            )
        )
    )


@pytest.fixture
def make_package(tmp_path):
    """
    Make a package from a given name, version and list of required packages.
    """

    def _make_package(name, version="0.1", install_requires=None):
        if install_requires is None:
            install_requires = []

        install_requires_str = "[{}]".format(
            ",".join("{!r}".format(package) for package in install_requires)
        )

        package_dir = tmp_path / "packages" / name / version
        package_dir.mkdir(parents=True)

        setup_file = str(package_dir / "setup.py")
        with open(setup_file, "w") as fp:
            fp.write(
                dedent(
                    """\
                    from setuptools import setup
                    setup(
                        name={name!r},
                        version={version!r},
                        install_requires={install_requires_str},
                    )
                    """.format(
                        name=name,
                        version=version,
                        install_requires_str=install_requires_str,
                    )
                )
            )
        return package_dir

    return _make_package


@pytest.fixture
def run_setup_file():
    """
    Run a setup.py file from a given package dir.
    """

    def _run_setup_file(package_dir_path, *args):
        setup_file = str(package_dir_path / "setup.py")
        return check_call(
            (sys.executable, setup_file) + args, cwd=str(package_dir_path)
        )  # nosec

    return _run_setup_file


@pytest.fixture
def make_wheel(run_setup_file):
    """
    Make a wheel distribution from a given package dir.
    """

    def _make_wheel(package_dir, dist_dir, *args):
        return run_setup_file(
            package_dir, "bdist_wheel", "--dist-dir", str(dist_dir), *args
        )

    return _make_wheel


@pytest.fixture
def make_sdist(run_setup_file):
    """
    Make a source distribution from a given package dir.
    """

    def _make_sdist(package_dir, dist_dir, *args):
        return run_setup_file(package_dir, "sdist", "--dist-dir", str(dist_dir), *args)

    return _make_sdist
