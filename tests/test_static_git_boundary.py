"""Static verification must not invoke Git's configured external code helpers."""
import os
import subprocess
import sys
from pathlib import Path

from reposhield.gitutil import diff_added_lines, diff_changes, diff_numstat


def test_git_diff_helpers_are_never_executed(demo_repo, tmp_path):
    marker = tmp_path / "helper-ran"
    helper = tmp_path / "helper.py"
    helper.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('unsafe')\n")
    # GIT_EXTERNAL_DIFF would run without --no-ext-diff. A textconv driver would
    # run on .gitattributes matches without --no-textconv, even for static diff.
    command = f'"{sys.executable}" "{helper}"'
    attributes = Path(demo_repo) / ".git" / "info" / "attributes"
    prior = attributes.read_bytes() if attributes.exists() else None
    env_prior = os.environ.get("GIT_EXTERNAL_DIFF")
    try:
        os.environ["GIT_EXTERNAL_DIFF"] = command
        subprocess.run(["git", "-C", demo_repo, "config", "diff.rsprobe.textconv", command], check=True)
        attributes.write_text("*.py diff=rsprobe\n")
        assert diff_changes(demo_repo, "main", "pr/safe-refactor")
        assert diff_numstat(demo_repo, "main", "pr/safe-refactor")
        assert diff_added_lines(demo_repo, "main", "pr/safe-refactor")
        assert not marker.exists()
    finally:
        if env_prior is None:
            os.environ.pop("GIT_EXTERNAL_DIFF", None)
        else:
            os.environ["GIT_EXTERNAL_DIFF"] = env_prior
        subprocess.run(["git", "-C", demo_repo, "config", "--unset", "diff.rsprobe.textconv"], check=True)
        if prior is None:
            attributes.unlink()
        else:
            attributes.write_bytes(prior)
