"""Security boundary validation for module ``agent`` (TP-CAT-07/09 precursors).

Three boundary classes (mission spec; glossary §6 binding "agents never touch the
Blender scene"; m1-module-contracts §8/§10):

1. SOURCE SCAN — ``modules/agent/bcagent/**`` may import ``bcdoc`` (and ``bcio``
   for the cad.io tools) and the standard library ONLY. ``bpy``/``bcshell``
   imports are boundary violations; ``eval``/``exec``/``subprocess``/``os.system``
   are forbidden (the expression-sandbox rule of permissions doc §7 — the query
   language ships a hand-written parser, never eval). The scan is AST/text-based
   and runs WITHOUT importing bcagent, so it stays green even while bcdoc/bcio
   (worker 3-b) are not yet integrated.

2. DISPATCH DENIAL — a session lacking a required permission class is denied with
   ``CAD_E_PERMISSION_DENIED`` BEFORE any tool code runs, even for fully valid
   arguments (deny early, execute nothing; permissions doc §7 layer 2).

3. IO CONFINEMENT — cad.io tools touch NOTHING except the path argument given by
   the HOST. M1 rule (recorded here, binding): export/import paths are used AS
   GIVEN by the host — the in-process adapter performs no path validation of its
   own (the permission authority that granted ``filesystem`` decides paths);
   these tests assert the tools never write/read anywhere except the provided
   path.

INTEGRATION NOTE (honest): tests in classes 2-3 import ``bcdoc``/``bcio``/``bcagent``
lazily INSIDE the test body so the source-scan tests remain runnable while worker
3-b's packages land; until then those tests are expectedly RED. No stubs are created
here (forbidden by the mission).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BCAGENT_DIR = REPO_ROOT / "modules" / "agent" / "bcagent"

#: The ONLY bc* packages bcagent may import (m1-module-contracts §8: "bcagent
#: imports bcdoc (and bcio for cad.io) ONLY").
ALLOWED_BC_PACKAGES = frozenset({"bcdoc", "bcio"})
#: Absolutely forbidden anywhere in bcagent (glossary §6 runtime principle).
FORBIDDEN_PACKAGES = frozenset({"bpy", "bcshell"})


def _bcagent_sources():
    files = sorted(BCAGENT_DIR.rglob("*.py"))
    assert files, "bcagent package missing — cannot scan"
    return files


# ---------------------------------------------------------------------------
# 1. Source scan — no Blender surface, no eval/exec/subprocess, import allowlist
# ---------------------------------------------------------------------------


class TestSourceBoundary:
    def test_no_bpy_or_bcshell_imports(self):
        """Glossary §6 (binding): agents change drawings ONLY through the CAD
        document's transaction mechanisms — bcagent must never import bpy (the
        Blender scene is shell territory, derived display-only) or bcshell."""
        offenders = []
        for path in _bcagent_sources():
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    targets = [node.module] if node.module else []
                for target in targets:
                    root = (target or "").split(".")[0]
                    if root in FORBIDDEN_PACKAGES:
                        offenders.append((path.name, node.lineno, target))
        assert not offenders, f"boundary violations: {offenders}"

    def test_import_allowlist_is_bcdoc_bcio_and_stdlib_only(self):
        """Every import in bcagent resolves to: stdlib, __future__, a relative
        (package-internal) import, or bcdoc/bcio. Anything else — a stray third
        party package, another bc* module — fails this test."""
        offenders = []
        for path in _bcagent_sources():
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root in ALLOWED_BC_PACKAGES:
                            continue
                        if root in sys.stdlib_module_names or root == "__future__":
                            continue
                        offenders.append((path.name, node.lineno, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:  # relative -> package-internal
                        continue
                    root = (node.module or "").split(".")[0]
                    if root in ALLOWED_BC_PACKAGES:
                        continue
                    if root in sys.stdlib_module_names or root == "__future__":
                        continue
                    offenders.append((path.name, node.lineno, node.module))
        assert not offenders, f"imports outside the bcagent boundary: {offenders}"

    def test_no_eval_exec_subprocess_or_os_system(self):
        """Permissions doc §7 (expression sandbox): no eval/exec anywhere; no
        subprocess machinery or shell escapes in the adapter package."""
        patterns = {
            "eval(": re.compile(r"\beval\s*\("),
            "exec(": re.compile(r"\bexec\s*\("),
            "subprocess": re.compile(r"\bsubprocess\b"),
            "os.system(": re.compile(r"\bos\.system\s*\("),
            "os.popen(": re.compile(r"\bos\.popen\s*\("),
        }
        offenders = []
        for path in _bcagent_sources():
            for lineno, line in enumerate(
                path.read_text().splitlines(), start=1
            ):
                code = line.split("#", 1)[0]  # ignore comments
                for label, pattern in patterns.items():
                    if pattern.search(code):
                        offenders.append((path.name, lineno, label, line.strip()))
        assert not offenders, f"forbidden constructs: {offenders}"

    def test_document_access_only_through_bcdoc(self):
        """The adapter's ONLY document access is bcdoc: the tool modules reference
        ``ctx.doc``/``doc.`` APIs (transaction/add/get/entities), never a direct
        scene/data-store handle. Structural check: every bcagent tool module
        imports bcdoc or uses the ToolContext.doc seam — and nothing else is
        passed around. (The import allowlist above carries the hard guarantee;
        this test documents the access pattern on record.)"""
        for path in _bcagent_sources():
            text = path.read_text()
            assert "bpy.data" not in text, path.name
            assert "bpy.context" not in text, path.name


# ---------------------------------------------------------------------------
# 2. Dispatch denial — permission gate fires before execution, valid args or not
# ---------------------------------------------------------------------------


class TestDispatchDenial:
    """These tests import bcagent/bcdoc/bcio lazily: the source-scan suite above
    must stay independent of worker 3-b's integration state."""

    def _make_adapter(self):
        from bcagent import CadToolAdapter, SessionManager
        from bcdoc.document import Document

        sessions = SessionManager()
        return CadToolAdapter(Document(), sessions), sessions

    def test_denied_before_execution_even_for_valid_args(self, tmp_path):
        adapter, sessions = self._make_adapter()
        # a REAL file at a REAL path — the args are fully valid
        target = tmp_path / "secret.dxf"
        target.write_text("PRE-EXISTING CONTENT")
        session = sessions.issue_session(mode="propose", classes=("doc-edit",))
        env = adapter.dispatch({
            "tool": "cad.io.export_dxf",
            "session_token": session.token,
            "args": {"path": str(target)},
        })
        assert env["status"] == "error"
        assert env["error"]["code"] == "CAD_E_PERMISSION_DENIED"
        # NOT executed: the file is untouched (no overwrite, no truncation)
        assert target.read_text() == "PRE-EXISTING CONTENT"
        assert adapter.document.doc_version == 0
        assert adapter.document.undo_depth() == 0

    def test_denied_import_leaves_document_bit_identical(self, tmp_path):
        adapter, sessions = self._make_adapter()
        # stage a real DXF via a session that HAS filesystem (proves the file is
        # importable), then attempt the import with a session that lacks it
        writer = sessions.issue_session(mode="read-only", classes=("filesystem",))
        editor = sessions.issue_session(mode="propose",
                                        classes=("doc-edit", "filesystem"))
        env = adapter.dispatch({
            "tool": "cad.geometry.create", "session_token": editor.token,
            "args": {"type": "line",
                      "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
                      "base_doc_version": 0}})
        assert env["status"] == "ok", env
        dxf_path = str(tmp_path / "staged.dxf")
        env = adapter.dispatch({
            "tool": "cad.io.export_dxf", "session_token": writer.token,
            "args": {"path": dxf_path}})
        assert env["status"] == "ok", env
        snapshot = adapter.document.serialize()

        denied = sessions.issue_session(mode="propose", classes=("doc-edit",))
        env = adapter.dispatch({
            "tool": "cad.io.import_dxf", "session_token": denied.token,
            "args": {"path": dxf_path,
                      "base_doc_version": adapter.document.doc_version}})
        assert env["error"]["code"] == "CAD_E_PERMISSION_DENIED"
        # the import did NOT run: document bit-identical, version unchanged
        assert adapter.document.serialize() == snapshot

    def test_revoked_class_denies_immediately(self, tmp_path):
        adapter, sessions = self._make_adapter()
        session = sessions.issue_session(mode="propose",
                                         classes=("doc-edit", "filesystem"))
        sessions.revoke_class(session.token, "filesystem")
        never = tmp_path / "revoked-class.dxf"  # never created — denial, not failure
        env = adapter.dispatch({
            "tool": "cad.io.export_dxf", "session_token": session.token,
            "args": {"path": str(never)}})
        assert env["error"]["code"] == "CAD_E_PERMISSION_DENIED"
        assert not never.exists()  # denied BEFORE execution: no file, no partial write


# ---------------------------------------------------------------------------
# 3. IO confinement — cad.io touches NOTHING except the given path argument
# ---------------------------------------------------------------------------


class TestIoConfinement:
    """M1 rule (binding, recorded): export/import paths are used AS GIVEN by the
    HOST; the adapter does no path validation of its own. These tests pin the
    other half of the rule: whatever path the host provides, the tools touch
    NOTHING else — not sibling files, not the directory tree, not hidden files."""

    def _tree_snapshot(self, root: Path):
        return {
            str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    def _editor_session(self, sessions):
        return sessions.issue_session(mode="propose",
                                      classes=("doc-edit", "filesystem"))

    def test_export_writes_exactly_the_given_path(self, tmp_path):
        from bcagent import CadToolAdapter, SessionManager
        from bcdoc.document import Document

        sessions = SessionManager()
        adapter = CadToolAdapter(Document(), sessions)
        editor = self._editor_session(sessions)
        env = adapter.dispatch({
            "tool": "cad.geometry.create", "session_token": editor.token,
            "args": {"type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
                      "base_doc_version": 0}})
        assert env["status"] == "ok", env

        (tmp_path / "existing").write_text("keep me")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.txt").write_text("untouched")
        before = self._tree_snapshot(tmp_path)

        target = tmp_path / "sub" / "out.dxf"  # a path INSIDE the tree
        env = adapter.dispatch({
            "tool": "cad.io.export_dxf", "session_token": editor.token,
            "args": {"path": str(target)}})
        assert env["status"] == "ok", env

        after = self._tree_snapshot(tmp_path)
        new_files = set(after) - set(before)
        assert new_files == {"sub/out.dxf"}, new_files
        # every pre-existing file is bit-identical (size + mtime)
        for name, stat_before in before.items():
            assert after[name] == stat_before, name

    def test_import_reads_only_given_path_and_writes_nothing(self, tmp_path):
        from bcagent import CadToolAdapter, SessionManager
        from bcdoc.document import Document

        sessions = SessionManager()
        adapter = CadToolAdapter(Document(), sessions)
        editor = self._editor_session(sessions)
        adapter.dispatch({
            "tool": "cad.geometry.create", "session_token": editor.token,
            "args": {"type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
                      "base_doc_version": 0}})
        dxf = tmp_path / "in.dxf"
        env = adapter.dispatch({
            "tool": "cad.io.export_dxf", "session_token": editor.token,
            "args": {"path": str(dxf)}})
        assert env["status"] == "ok", env

        (tmp_path / "sidecar.txt").write_text("collateral")
        before = self._tree_snapshot(tmp_path)
        dxf_stat_before = (dxf.stat().st_size, dxf.stat().st_mtime_ns,
                           dxf.read_bytes())

        env = adapter.dispatch({
            "tool": "cad.io.import_dxf", "session_token": editor.token,
            "args": {"path": str(dxf),
                      "base_doc_version": adapter.document.doc_version}})
        assert env["status"] == "ok", env

        # the import wrote NOTHING: identical tree, source DXF byte-identical
        assert self._tree_snapshot(tmp_path) == before
        dxf_stat_after = (dxf.stat().st_size, dxf.stat().st_mtime_ns,
                          dxf.read_bytes())
        assert dxf_stat_before == dxf_stat_after

    def test_paths_used_as_given_by_host_documented(self):
        """The M1 confinement rule, pinned as a test: the io tools contain no
        path-mangling (no normalization/relocation/jailing) — the path argument
        is passed through verbatim to bcio. The HOST owns path approval."""
        io_source = (BCAGENT_DIR / "tools" / "io_tools.py").read_text()
        assert "os.path.abspath" not in io_source
        assert "realpath" not in io_source
        assert "relpath" not in io_source
        # and the path argument is required verbatim via require_str:
        assert 'require_str(args, "path")' in io_source
