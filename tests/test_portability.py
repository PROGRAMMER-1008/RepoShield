"""Regression tests for problems found on a real Windows / older-Python-3.10 machine."""
import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

from reposhield import gitutil
from reposhield.cli import main
from reposhield.demo import build_demo, rmtree_force
from reposhield.engine import state_dir_for


def test_export_tree_works_when_tarfile_has_no_filter_argument(demo_repo, tmp_path, monkeypatch):
    """Python < 3.10.12 / 3.11.4: TarFile.extractall() has no `filter=` -> used to raise TypeError."""
    original = tarfile.TarFile.extractall

    def old_extractall(self, path=".", members=None, *, numeric_owner=False):      # note: no `filter`
        return original(self, path, members, numeric_owner=numeric_owner)

    monkeypatch.setattr(tarfile.TarFile, "extractall", old_extractall)
    dest = tmp_path / "ws"
    gitutil.export_tree(demo_repo, "main", str(dest))
    assert (dest / "payments" / "refund.py").exists() and (dest / ".reposhield.yml").exists()


def test_extraction_guard_skips_path_traversal_and_links(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in [("ok/a.txt", b"hi"), ("../evil.txt", b"x"), ("/abs.txt", b"x")]:
            ti = tarfile.TarInfo(name); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
        link = tarfile.TarInfo("ln"); link.type = tarfile.SYMTYPE; link.linkname = "/etc/passwd"; tf.addfile(link)
    buf.seek(0)
    dest = tmp_path / "d"; dest.mkdir()
    with tarfile.open(fileobj=buf) as tf:
        names = [m.name for m in gitutil._safe_members(tf, str(dest))]
    assert names == ["ok/a.txt"]


def test_rmtree_force_removes_read_only_trees(tmp_path):
    d = tmp_path / "x" / "objects"; d.mkdir(parents=True)
    f = d / "blob"; f.write_text("data")
    os.chmod(f, stat.S_IREAD)                    # like git's read-only object files
    os.chmod(d, stat.S_IREAD | stat.S_IEXEC)
    rmtree_force(str(tmp_path / "x"))
    assert not (tmp_path / "x").exists()


def test_demo_can_be_rebuilt_over_itself(tmp_path):
    dest = str(tmp_path / "demo")
    build_demo(dest)
    build_demo(dest)                             # second run used to fail with WinError 5
    assert os.path.exists(os.path.join(dest, "payments", "refund.py"))


def test_demo_refuses_to_delete_unrelated_folders_unless_forced(tmp_path):
    victim = tmp_path / "my-work"; victim.mkdir(); (victim / "thesis.docx").write_text("precious")
    with pytest.raises(RuntimeError, match="does not look like"):
        build_demo(str(victim))
    assert (victim / "thesis.docx").exists()
    build_demo(str(victim), force=True)
    assert not (victim / "thesis.docx").exists() and (victim / "payments").exists()


def test_demo_refuses_when_terminal_is_inside_target(tmp_path, monkeypatch):
    dest = str(tmp_path / "demo")
    build_demo(dest)
    monkeypatch.chdir(dest)
    with pytest.raises(RuntimeError, match="cd out"):
        build_demo(dest)


def test_showcase_prints_table_and_writes_html_index(demo_repo, capsys):
    rc = main(["-C", demo_repo, "showcase", "--sandbox", "subprocess"])
    out = capsys.readouterr().out
    assert rc == 0 and "DIFF" not in out and "pr/safe-refactor" in out and "REVIEW_REQUIRED" in out
    index = os.path.join(state_dir_for(demo_repo), "showcase.html")
    html = open(index, encoding="utf-8").read()
    assert html.count("report.html") == 10 and "pr/transitive-leak" in html
    runs = Path(state_dir_for(demo_repo)) / "runs"
    for logical_run in runs.iterdir():
        attempts = list(logical_run.iterdir())
        assert attempts
        assert all((attempt / "report.html").is_file() for attempt in attempts)
    reports = list(runs.glob("*/attempt_*/report.html"))
    assert len(reports) >= 10
    assert sum(report.as_uri() in html for report in reports) == 10
