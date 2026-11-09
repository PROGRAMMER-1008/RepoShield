import pytest
from reposhield.util import glob_match


@pytest.mark.parametrize("pat,path,ok", [
    ("payments/**", "payments/refund.py", True),
    ("payments/**", "payments/deep/x.py", True),
    ("payments/**", "orders/payments/x.py", False),
    ("*.pem", "keys/server.pem", True),
    ("*.pem", "server.pem", True),
    (".env", "svc/.env", True),
    (".github/workflows/**", ".github/workflows/ci.yml", True),
    ("tests/*/test_*.py", "tests/auth/test_login.py", True),
    ("tests/*/test_*.py", "tests/a/b/test_x.py", False),
    ("**/*.md", "README.md", True),
    ("docs/**", "docs/a/b.md", True),
    ("src/**/x.py", "src/x.py", True),
    ("/only-root.txt", "sub/only-root.txt", False),
])
def test_glob(pat, path, ok):
    assert glob_match(pat, path) is ok
