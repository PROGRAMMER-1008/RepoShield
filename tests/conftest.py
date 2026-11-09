import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from reposhield.demo import build_demo          # noqa: E402
from reposhield.engine import VerifyOptions, verify   # noqa: E402


@pytest.fixture(scope="session")
def demo_repo(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("demo") / "repo")
    build_demo(path)
    return path


@pytest.fixture
def run(demo_repo):
    def _run(branch, **kw):
        return verify(VerifyOptions(repo=demo_repo, base="main", head=branch, sandbox="subprocess", force=True, **kw))
    return _run
