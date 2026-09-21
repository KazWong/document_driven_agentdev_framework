from __future__ import annotations

import fnmatch
import json
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from .constants import ALL_STATES, PROTECTED_BRANCHES, RISK_POLICY, TRANSIENT_STATES
from .manifest import load_and_validate_manifest
from .util import (
    AgentEnvError, append_jsonl, atomic_write_json, atomic_write_text, dump_yaml,
    env_root, file_lock, git, git_branch, git_changed_paths, git_common_root,
    git_sha, git_status_paths, load_json, load_yaml, safe_actor, sha256_file,
    sha256_json, slugify, state_root, utc_now, workspace_root,
)


class WorkItem:
    """Authoritative project-local work-item record.

    Environment-level state contains only discovery/runtime data. The owning Git
    project's .agent/work-items/<id> directory is the canonical audit record.
    """

    def __init__(self, work_id: str, project_root: Path, root: Path | None = None) -> None:
        self.state_root = (root or state_root()).resolve()
        self.work_id = work_id
        self.project_root = git_common_root(project_root).resolve()
        self.project_agent_root = self.project_root / ".agent"
        self.path = self.project_agent_root / "work-items" / work_id
        self.manifest_path = self.path / "work-item.yaml"
        self.status_path = self.path / "status.json"
        self.trace_path = self.path / "trace.jsonl"
        self.lock_path = self.path / ".lock"
        self.documents_path = self.path / "documents"
        self.plans_path = self.path / "plans"
        self.artifacts_path = self.path / "artifacts"
        self.runs_path = self.path / "runs"
        self.approvals_path = self.path / "approvals"
        self.evidence_index_path = self.path / "evidence-index.json"

    @staticmethod
    def _project_from_cwd() -> Path | None:
        try:
            return git_common_root(Path.cwd())
        except AgentEnvError:
            return None

    @staticmethod
    def _index_path(root: Path | None = None) -> Path:
        return (root or state_root()).resolve() / "index" / "work-items.json"

    @classmethod
    def _lookup_index(cls, work_id: str, root: Path | None = None) -> Path | None:
        path = cls._index_path(root)
        if not path.is_file():
            return None
        try:
            data = load_json(path)
        except AgentEnvError:
            return None
        entry = data.get("work_items", {}).get(work_id)
        if not isinstance(entry, dict) or not entry.get("project"):
            return None
        project = Path(str(entry["project"])).resolve()
        return project if project.is_dir() else None

    def _register_index(self) -> None:
        path = self._index_path(self.state_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path.with_suffix(".lock")):
            if path.is_file():
                try:
                    data = load_json(path)
                except AgentEnvError:
                    data = {}
            else:
                data = {}
            items = dict(data.get("work_items", {}))
            items[self.work_id] = {
                "project": str(self.project_root),
                "work_item": str(self.path),
                "updated_at": utc_now(),
            }
            atomic_write_json(path, {"schema_version": 1, "work_items": items})

    @classmethod
    def _ensure_project_control(cls, project_root: Path) -> None:
        project_root = git_common_root(project_root)
        agent_root = project_root / ".agent"
        agent_root.mkdir(parents=True, exist_ok=True)
        (agent_root / "work-items").mkdir(parents=True, exist_ok=True)
        project_yaml = agent_root / "project.yaml"
        if not project_yaml.is_file():
            dump_yaml(project_yaml, {
                "schema_version": 1,
                "name": project_root.name,
                "repository": str(project_root),
                "scm": {"provider": None, "remote": "origin", "base_branch": "main"},
            })
        branching = agent_root / "branching-policy.md"
        template = env_root() / "templates" / "common" / ".agent" / "branching-policy.md"
        if not branching.is_file() and template.is_file():
            shutil.copy2(template, branching)
        gitignore = project_root / ".gitignore"
        current = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
        additions: list[str] = []
        for line in ("/.agent/work-items/", "/.agent-context/", "/.test-results/"):
            if line not in current.splitlines():
                additions.append(line)
        if additions:
            prefix = "" if not current or current.endswith("\n") else "\n"
            atomic_write_text(gitignore, current + prefix + "\n# Agent framework local state\n" + "\n".join(additions) + "\n")

        # Runtime data must remain ignored even when the project predates the
        # generated .gitignore or a linked worktree was created from an older
        # commit. Git's common info/exclude applies to the canonical checkout
        # and every linked worktree without mutating project history.
        exclude_path = project_root / ".git" / "info" / "exclude"
        if exclude_path.parent.is_dir():
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            exclude = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
            runtime_patterns = (
                ".agent/work-items/", ".agent-context/", ".test-results/",
                "build/", "install/", "log/",
            )
            missing = [pattern for pattern in runtime_patterns if pattern not in exclude.splitlines()]
            if missing:
                prefix = "" if not exclude or exclude.endswith("\n") else "\n"
                atomic_write_text(
                    exclude_path,
                    exclude + prefix + "\n# Robotics agent runtime/generated state\n" + "\n".join(missing) + "\n",
                )

    @classmethod
    def create(cls, manifest_source: Path, *, root: Path | None = None) -> "WorkItem":
        manifest = load_and_validate_manifest(manifest_source)
        repository = git_common_root(Path(manifest["repository"]))
        cls._ensure_project_control(repository)
        item = cls(manifest["id"], repository, root=root)
        if item.path.exists():
            raise AgentEnvError(f"work item already exists: {item.work_id}")
        for path in (
            item.path, item.documents_path, item.plans_path, item.artifacts_path,
            item.runs_path, item.approvals_path, item.path / "evidence",
        ):
            path.mkdir(parents=True, exist_ok=True)
        dump_yaml(item.manifest_path, manifest)
        dump_yaml(item.documents_path / "index.yaml", {"schema_version": 1, "documents": {}})
        baseline = git_sha(repository, manifest["base_branch"])
        status = {
            "schema_version": 1,
            "id": item.work_id,
            "title": manifest["title"],
            "risk_class": manifest["risk_class"],
            "project_kind": manifest["project_kind"],
            "state": "INTAKE",
            "last_stable_state": "INTAKE",
            "revision": 1,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "manifest_sha256": sha256_file(item.manifest_path),
            "repository": str(repository),
            "base_branch": manifest["base_branch"],
            "branch": None,
            "worktree": None,
            "baseline_sha": baseline,
            "document_revision": 0,
            "active_document_set_sha256": sha256_json([]),
            "current_plan": None,
            "implementation": None,
            "pull_request": None,
            "last_error": None,
            "role_runs": {},
            "ci": None,
            "merge": None,
            "promotion": None,
            "gate_epochs": {"plan": 0, "merge": 0, "hardware": 0},
        }
        atomic_write_json(item.status_path, status)
        item._append_trace("work_item_created", None, "INTAKE", {
            "manifest_sha256": status["manifest_sha256"], "repository": str(repository)
        })
        item._register_index()
        item.refresh_evidence_index()
        return item

    @classmethod
    def _migrate_legacy(cls, work_id: str, root: Path | None = None) -> "WorkItem" | None:
        state = (root or state_root()).resolve()
        legacy = state / "work-items" / work_id
        status_path = legacy / "status.json"
        if not status_path.is_file():
            return None
        status = load_json(status_path)
        repository = git_common_root(Path(status["repository"]))
        cls._ensure_project_control(repository)
        item = cls(work_id, repository, root=root)
        if item.path.exists():
            return item
        shutil.copytree(legacy, item.path)
        old_manifest = item.path / "request.yaml"
        if old_manifest.is_file() and not item.manifest_path.exists():
            old_manifest.rename(item.manifest_path)
        for path in (item.documents_path, item.plans_path, item.artifacts_path, item.runs_path, item.approvals_path, item.path / "evidence"):
            path.mkdir(parents=True, exist_ok=True)
        if not (item.documents_path / "index.yaml").is_file():
            dump_yaml(item.documents_path / "index.yaml", {"schema_version": 1, "documents": {}})
        migrated = item.status
        migrated.setdefault("document_revision", 0)
        migrated.setdefault("active_document_set_sha256", sha256_json([]))
        migrated.setdefault("current_plan", None)
        migrated.setdefault("implementation", None)
        migrated.setdefault("pull_request", None)
        migrated.setdefault("merge", None)
        migrated.setdefault("gate_epochs", {"plan": 0, "merge": 0, "hardware": 0})
        atomic_write_json(item.status_path, migrated)
        archive = state / "legacy-work-items" / f"{work_id}-{utc_now().replace(':', '').replace('+00:00', 'Z')}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(archive))
        item._append_trace("legacy_work_item_migrated", migrated.get("state"), migrated.get("state"), {
            "legacy_archive": str(archive), "project": str(repository)
        })
        item._register_index()
        item.refresh_evidence_index()
        return item

    @classmethod
    def open(cls, work_id: str, root: Path | None = None) -> "WorkItem":
        current = cls._project_from_cwd()
        if current is not None:
            cls._ensure_project_control(current)
            candidate = cls(work_id, current, root=root)
            if candidate.status_path.is_file():
                candidate._register_index()
                return candidate
        indexed = cls._lookup_index(work_id, root=root)
        if indexed is not None:
            cls._ensure_project_control(indexed)
            item = cls(work_id, indexed, root=root)
            if item.status_path.is_file():
                return item
        migrated = cls._migrate_legacy(work_id, root=root)
        if migrated is not None:
            return migrated
        raise AgentEnvError(f"unknown work item: {work_id}")

    @property
    def manifest(self) -> dict[str, Any]:
        return load_yaml(self.manifest_path)

    @property
    def status(self) -> dict[str, Any]:
        status = load_json(self.status_path)
        if status.get("state") not in ALL_STATES:
            raise AgentEnvError(f"invalid workflow state: {status.get('state')!r}")
        return status

    @property
    def repo(self) -> Path:
        status = self.status
        return Path(status.get("worktree") or status["repository"]).resolve()

    @property
    def policy(self) -> dict[str, Any]:
        return RISK_POLICY[self.status["risk_class"]]

    def _append_trace(
        self, event: str, from_state: str | None, to_state: str | None,
        metadata: dict[str, Any] | None = None, actor: str | None = None,
    ) -> None:
        append_jsonl(self.trace_path, {
            "timestamp": utc_now(), "work_item": self.work_id, "event": event,
            "actor": actor or os.environ.get("USER") or "system",
            "from_state": from_state, "to_state": to_state, "metadata": metadata or {},
        })

    def transition(
        self, expected: str | set[str], target: str, *, event: str,
        metadata: dict[str, Any] | None = None, error: str | None = None,
    ) -> dict[str, Any]:
        expected_states = {expected} if isinstance(expected, str) else set(expected)
        if target not in ALL_STATES:
            raise AgentEnvError(f"invalid target state: {target}")
        with file_lock(self.lock_path):
            status = self.status
            current = status["state"]
            if current not in expected_states:
                raise AgentEnvError(
                    f"cannot transition {self.work_id} from {current} to {target}; expected {', '.join(sorted(expected_states))}"
                )
            status["state"] = target
            status["revision"] = int(status.get("revision", 0)) + 1
            status["updated_at"] = utc_now()
            status["last_error"] = error
            if target not in TRANSIENT_STATES:
                status["last_stable_state"] = target
            atomic_write_json(self.status_path, status)
            self._append_trace(event, current, target, metadata)
        self.refresh_evidence_index()
        return status

    def update_status(self, updates: dict[str, Any], *, event: str) -> dict[str, Any]:
        with file_lock(self.lock_path):
            status = self.status
            state = status["state"]
            status.update(updates)
            status["revision"] = int(status.get("revision", 0)) + 1
            status["updated_at"] = utc_now()
            atomic_write_json(self.status_path, status)
            self._append_trace(event, state, state, updates)
        self._register_index()
        self.refresh_evidence_index()
        return status

    # ---------- documents / planning ----------
    def _document_index(self) -> dict[str, Any]:
        path = self.documents_path / "index.yaml"
        if not path.is_file():
            return {"schema_version": 1, "documents": {}}
        data = load_yaml(path)
        if not isinstance(data.get("documents"), dict):
            data["documents"] = {}
        return data

    def active_documents(self) -> list[dict[str, Any]]:
        index = self._document_index()
        active: list[dict[str, Any]] = []
        for doc_id, record in sorted(index["documents"].items()):
            if not isinstance(record, dict):
                continue
            revision = record.get("active_revision")
            revisions = record.get("revisions", [])
            match = next((r for r in revisions if isinstance(r, dict) and r.get("revision") == revision), None)
            if not match:
                continue
            entry = dict(match)
            entry["id"] = doc_id
            entry["path"] = str((self.documents_path / doc_id / revision / entry["filename"]).resolve())
            active.append(entry)
        return active

    def active_document_set_sha256(self) -> str:
        values = [
            {"id": d["id"], "revision": d["revision"], "sha256": d["sha256"], "filename": d["filename"]}
            for d in self.active_documents()
        ]
        return sha256_json(values)

    def import_documents(self, sources: Iterable[Path], supersedes: str | None = None) -> list[dict[str, Any]]:
        source_paths = [Path(p).expanduser().resolve() for p in sources]
        if supersedes and len(source_paths) != 1:
            raise AgentEnvError("--supersedes requires exactly one --document")
        if not source_paths:
            raise AgentEnvError("at least one document is required")
        index = self._document_index()
        documents = dict(index.get("documents", {}))
        imported: list[dict[str, Any]] = []
        for source in source_paths:
            if not source.is_file():
                raise AgentEnvError(f"document does not exist: {source}")
            if supersedes:
                doc_id = supersedes.upper()
                if doc_id not in documents:
                    raise AgentEnvError(f"cannot supersede unknown document: {doc_id}")
            else:
                used = [int(m.group(1)) for key in documents for m in [re.fullmatch(r"DOC-(\d+)", key)] if m]
                doc_id = f"DOC-{max(used, default=0) + 1:03d}"
                documents[doc_id] = {"active_revision": None, "revisions": []}
            record = dict(documents[doc_id])
            revisions = list(record.get("revisions", []))
            revision = f"r{len(revisions) + 1:03d}"
            dest_dir = self.documents_path / doc_id / revision
            dest_dir.mkdir(parents=True, exist_ok=False)
            dest = dest_dir / source.name
            shutil.copy2(source, dest)
            media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            metadata = {
                "revision": revision,
                "filename": source.name,
                "source_path": str(source),
                "media_type": media_type,
                "size": dest.stat().st_size,
                "sha256": sha256_file(dest),
                "imported_at": utc_now(),
            }
            revisions.append(metadata)
            record["revisions"] = revisions
            record["active_revision"] = revision
            documents[doc_id] = record
            imported.append({"id": doc_id, **metadata})
        dump_yaml(self.documents_path / "index.yaml", {"schema_version": 1, "documents": documents})
        digest = self.active_document_set_sha256()
        status = self.status
        self.update_status({
            "document_revision": int(status.get("document_revision", 0)) + 1,
            "active_document_set_sha256": digest,
            "current_plan": None,
            "implementation": None,
            "pull_request": None,
            "ci": None,
            "merge": None,
            "last_error": None,
        }, event="work_item_documents_updated")
        self.invalidate_gates({"plan", "merge", "hardware"}, event="document_update_invalidated_gates")
        current = self.status["state"]
        if current != "INTAKE":
            self.transition(current, "INTAKE", event="document_update_requires_replan", metadata={
                "documents": [{"id": d["id"], "revision": d["revision"]} for d in imported]
            })
        self._append_trace("documents_imported", self.status["state"], self.status["state"], {"documents": imported})
        self.refresh_evidence_index()
        return imported

    def prepare_agent_context(self) -> dict[str, Any]:
        root = self.repo / ".agent-context" / self.work_id
        if root.exists():
            shutil.rmtree(root)
        docs_root = root / "documents"
        docs_root.mkdir(parents=True, exist_ok=True)
        context_docs: list[dict[str, Any]] = []
        for document in self.active_documents():
            source = Path(document["path"])
            if sha256_file(source) != document["sha256"]:
                raise AgentEnvError(f"authoritative document hash mismatch: {document['id']}/{document['revision']}")
            dest_dir = docs_root / document["id"] / document["revision"]
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / document["filename"]
            shutil.copy2(source, dest)
            entry = {k: document[k] for k in ("id", "revision", "filename", "media_type", "size", "sha256")}
            entry["path"] = str(dest.relative_to(self.repo))
            context_docs.append(entry)
        dump_yaml(root / "index.yaml", {
            "schema_version": 1,
            "work_item": self.work_id,
            "active_document_set_sha256": self.active_document_set_sha256(),
            "documents": context_docs,
        })
        branching = self.project_agent_root / "branching-policy.md"
        branching_path: str | None = None
        if branching.is_file():
            staged = root / "branching-policy.md"
            shutil.copy2(branching, staged)
            branching_path = str(staged.relative_to(self.repo))
        return {
            "root": str(root.relative_to(self.repo)),
            "active_document_set_sha256": self.active_document_set_sha256(),
            "documents": context_docs,
            "branching_policy": branching_path,
        }

    def write_plan(self, text: str) -> Path:
        self.plans_path.mkdir(parents=True, exist_ok=True)
        nums = []
        for p in self.plans_path.glob("plan-*.md"):
            m = re.fullmatch(r"plan-(\d+)\.md", p.name)
            if m:
                nums.append(int(m.group(1)))
        num = max(nums, default=0) + 1
        plan_id = f"plan-{num:04d}"
        plan_path = self.plans_path / f"{plan_id}.md"
        inputs_path = self.plans_path / f"{plan_id}.inputs.yaml"
        atomic_write_text(plan_path, text.rstrip() + "\n")
        docs = [
            {"id": d["id"], "revision": d["revision"], "filename": d["filename"], "sha256": d["sha256"]}
            for d in self.active_documents()
        ]
        inputs = {
            "schema_version": 1,
            "work_item": self.work_id,
            "plan_id": plan_id,
            "repository_sha": git_sha(self.repo),
            "baseline_sha": self.status.get("baseline_sha"),
            "active_document_set_sha256": self.active_document_set_sha256(),
            "documents": docs,
            "created_at": utc_now(),
        }
        dump_yaml(inputs_path, inputs)
        current = {
            "id": plan_id,
            "path": str(plan_path.relative_to(self.path)),
            "sha256": sha256_file(plan_path),
            "inputs_path": str(inputs_path.relative_to(self.path)),
            "inputs_sha256": sha256_file(inputs_path),
            "active_document_set_sha256": inputs["active_document_set_sha256"],
            "repository_sha": inputs["repository_sha"],
        }
        self.update_status({"current_plan": current}, event="plan_revision_recorded")
        self.write_artifact("plan.md", text)
        return plan_path

    def retry_plan(self) -> None:
        state = self.status["state"]
        if state not in {"BLOCKED", "INTAKE"}:
            raise AgentEnvError(f"plan --retry requires BLOCKED or INTAKE, current state is {state}")
        if not self.active_documents():
            raise AgentEnvError(f"{self.work_id} has no active documents; import documents before retrying the plan")
        self.invalidate_gates({"plan", "merge", "hardware"}, event="plan_retry_invalidated_gates")
        self.update_status({"current_plan": None, "implementation": None, "pull_request": None, "ci": None, "merge": None}, event="plan_retry_reset")
        if state == "BLOCKED":
            self.transition("BLOCKED", "INTAKE", event="plan_retry_requested")

    # ---------- worktree / candidate ----------
    def create_worktree(self, branch: str | None = None) -> Path:
        manifest = self.manifest
        status = self.status
        if status.get("worktree"):
            existing = Path(status["worktree"])
            if existing.is_dir():
                return existing
            self.update_status({"worktree": None}, event="stale_worktree_reference_cleared")
            status = self.status
        repository = self.project_root
        strategy = manifest["isolation"]["strategy"]
        if strategy == "in-place":
            current = git_branch(repository)
            if current in PROTECTED_BRANCHES:
                raise AgentEnvError(f"in-place work is forbidden on protected branch '{current}'")
            self.update_status({"branch": current, "worktree": str(repository)}, event="in_place_isolation_accepted")
            return repository
        branch_name = branch or status.get("branch") or f"agent/{self.work_id.lower()}-{slugify(manifest['title'])}"
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", branch_name):
            raise AgentEnvError(f"invalid Git branch name: {branch_name}")
        worktree = (self.state_root / "worktrees" / repository.name / self.work_id).resolve()
        if worktree.exists():
            raise AgentEnvError(f"worktree path already exists: {worktree}")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        branch_exists = git(repository, "show-ref", "--verify", f"refs/heads/{branch_name}", check=False).returncode == 0
        args = ["worktree", "add"]
        if not branch_exists:
            args += ["-b", branch_name]
        args += [str(worktree), branch_name if branch_exists else manifest["base_branch"]]
        completed = git(repository, *args, check=False)
        if completed.returncode != 0:
            raise AgentEnvError(f"failed to create worktree: {(completed.stderr or completed.stdout).strip()}")
        self.update_status({
            "branch": branch_name, "worktree": str(worktree),
            "baseline_sha": status.get("baseline_sha") or git_sha(repository, manifest["base_branch"]),
        }, event="worktree_created")
        return worktree

    def ensure_implementation_isolation(self) -> None:
        manifest = self.manifest
        status = self.status
        if manifest["isolation"]["strategy"] == "worktree" and not status.get("worktree"):
            self.create_worktree()
        branch = git_branch(self.repo)
        if branch in PROTECTED_BRANCHES:
            raise AgentEnvError(f"implementation is forbidden on protected branch '{branch}'")

    def _path_is_in_scope(self, path: str) -> bool:
        scope = self.manifest["scope"]
        included = any(_path_matches(path, pattern) for pattern in scope["include"])
        excluded = any(_path_matches(path, pattern) for pattern in scope.get("exclude", []))
        return included and not excluded

    def scope_violations(self) -> list[str]:
        return [p for p in git_changed_paths(self.repo, baseline=self.status.get("baseline_sha")) if not self._path_is_in_scope(p)]

    def create_candidate_commit(self, *, expected_head: str | None = None) -> str:
        self.ensure_implementation_isolation()
        branch = git_branch(self.repo)
        if branch in PROTECTED_BRANCHES:
            raise AgentEnvError(f"candidate commits are forbidden on protected branch '{branch}'")
        if expected_head and git_sha(self.repo) != expected_head:
            raise AgentEnvError("coder changed Git history; the framework exclusively owns candidate commits")
        changed = git_status_paths(self.repo)
        if not changed:
            raise AgentEnvError("coder produced no implementation changes; refusing to create an empty candidate")
        out_of_scope = [p for p in changed if not self._path_is_in_scope(p)]
        if out_of_scope:
            raise AgentEnvError("candidate contains paths outside approved scope: " + ", ".join(out_of_scope))
        staged = git(self.repo, "add", "-A", "--", *changed, check=False)
        if staged.returncode != 0:
            raise AgentEnvError(f"failed to stage candidate implementation: {(staged.stderr or staged.stdout).strip()}")
        diff_check = git(self.repo, "diff", "--cached", "--check", check=False)
        if diff_check.returncode != 0:
            raise AgentEnvError("candidate diff check failed:\n" + (diff_check.stdout.strip() or diff_check.stderr.strip()))
        has_delta = git(self.repo, "diff", "--cached", "--quiet", "--", check=False)
        if has_delta.returncode == 0:
            raise AgentEnvError("coder produced no staged implementation delta")
        if has_delta.returncode != 1:
            raise AgentEnvError("cannot inspect staged candidate")
        had_prior = isinstance(self.status.get("implementation"), dict) or (expected_head and expected_head != self.status.get("baseline_sha"))
        commit_type = "fix" if had_prior else "feat"
        summary = re.sub(r"\s+", " ", self.manifest["title"]).strip()[:72].rstrip()
        message = f"{commit_type}({self.work_id}): {summary}"
        committed = git(
            self.repo, "-c", "user.name=Robotics Agent Framework",
            "-c", "user.email=robotics-agent@localhost", "commit", "-m", message, check=False,
        )
        if committed.returncode != 0:
            raise AgentEnvError(f"failed to create candidate commit: {(committed.stderr or committed.stdout).strip()}")
        candidate = git_sha(self.repo)
        if not candidate:
            raise AgentEnvError("candidate commit SHA is unavailable")
        implementation = {
            "baseline_sha": self.status.get("baseline_sha"), "candidate_sha": candidate,
            "local_test_sha": None, "integration_test_sha": None, "reviewed_sha": None,
            "commit_message": message, "created_at": utc_now(),
        }
        self.update_status({"implementation": implementation, "pull_request": None, "ci": None, "merge": None}, event="candidate_commit_created")
        self.assert_candidate_unchanged()
        return candidate

    def candidate_sha(self) -> str | None:
        implementation = self.status.get("implementation")
        if isinstance(implementation, dict) and implementation.get("candidate_sha"):
            return str(implementation["candidate_sha"])
        return None

    def assert_candidate_unchanged(self) -> str:
        candidate = self.candidate_sha()
        if not candidate:
            raise AgentEnvError("no candidate implementation commit is recorded")
        current = git_sha(self.repo)
        if current != candidate:
            raise AgentEnvError(f"worktree HEAD {current} differs from candidate commit {candidate}")
        tracked = git(self.repo, "status", "--porcelain=v1", "--untracked-files=no", check=True).stdout
        if tracked.strip():
            raise AgentEnvError("tracked files changed after the candidate commit")
        untracked = git(self.repo, "ls-files", "--others", "--exclude-standard", "-z", check=True).stdout.split("\0")
        scoped = [p for p in untracked if p and self._path_is_in_scope(p)]
        if scoped:
            raise AgentEnvError("new in-scope files appeared after candidate commit: " + ", ".join(sorted(scoped)))
        return candidate

    def record_candidate_stage(self, stage: str, candidate_sha: str | None = None) -> str:
        field = {"local": "local_test_sha", "integration": "integration_test_sha", "review": "reviewed_sha"}.get(stage)
        if not field:
            raise AgentEnvError("candidate stage must be local, integration, or review")
        candidate = self.assert_candidate_unchanged()
        if candidate_sha and candidate_sha != candidate:
            raise AgentEnvError(f"{stage} evidence SHA {candidate_sha} does not match candidate {candidate}")
        implementation = dict(self.status.get("implementation") or {})
        implementation[field] = candidate
        self.update_status({"implementation": implementation}, event=f"candidate_{stage}_verified")
        return candidate

    def require_publishable_candidate(self) -> str:
        candidate = self.assert_candidate_unchanged()
        implementation = self.status.get("implementation")
        if not isinstance(implementation, dict):
            raise AgentEnvError("candidate implementation record is missing")
        required = ["candidate_sha", "local_test_sha", "reviewed_sha"]
        if self.policy["requires_integration"]:
            required.append("integration_test_sha")
        values = {field: implementation.get(field) for field in required}
        if any(not value for value in values.values()):
            raise AgentEnvError("candidate is not publishable; missing SHA evidence: " + ", ".join(k for k, v in values.items() if not v))
        if set(map(str, values.values())) != {candidate}:
            raise AgentEnvError(f"candidate SHA evidence does not agree: {values}")
        return candidate

    # ---------- role runs / artifacts ----------
    def new_run_dir(self, role: str) -> Path:
        root = self.runs_path / role
        root.mkdir(parents=True, exist_ok=True)
        nums = [int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()]
        run = root / f"{max(nums, default=0) + 1:04d}"
        run.mkdir()
        return run

    def record_role_run(self, role: str, run_dir: Path, result: dict[str, Any], returncode: int) -> None:
        with file_lock(self.lock_path):
            status = self.status
            role_runs = dict(status.get("role_runs", {}))
            entries = list(role_runs.get(role, []))
            entries.append({
                "timestamp": utc_now(), "run_dir": str(run_dir.relative_to(self.path)),
                "returncode": returncode, "status": result.get("status"),
                "decision": result.get("decision"), "summary": result.get("summary"),
            })
            role_runs[role] = entries
            status["role_runs"] = role_runs
            status["revision"] = int(status.get("revision", 0)) + 1
            status["updated_at"] = utc_now()
            atomic_write_json(self.status_path, status)
        self._append_trace("role_run_recorded", self.status["state"], self.status["state"], {"role": role, "run": str(run_dir.relative_to(self.path))})
        self.refresh_evidence_index()

    def write_artifact(self, filename: str, text: str) -> Path:
        if Path(filename).name != filename:
            raise AgentEnvError("artifact filename must not contain path separators")
        path = self.artifacts_path / filename
        atomic_write_text(path, text.rstrip() + "\n")
        self.refresh_evidence_index()
        return path

    # ---------- gates / CI / lifecycle ----------
    def _approval_context(self, gate: str) -> tuple[str, dict[str, Any]]:
        status = self.status
        context: dict[str, Any] = {
            "work_item": self.work_id, "gate": gate,
            "gate_epoch": status.get("gate_epochs", {}).get(gate, 0),
            "manifest_sha256": sha256_file(self.manifest_path),
            "active_document_set_sha256": self.active_document_set_sha256(),
        }
        if gate == "plan":
            current = status.get("current_plan")
            if not isinstance(current, dict):
                raise AgentEnvError("plan approval requires a current immutable plan")
            context.update({"plan_id": current.get("id"), "plan_sha256": current.get("sha256"), "plan_inputs_sha256": current.get("inputs_sha256")})
        elif gate in {"merge", "hardware"}:
            ci = status.get("ci")
            candidate = self.candidate_sha()
            if not candidate:
                raise AgentEnvError(f"{gate} approval requires a candidate")
            if not isinstance(ci, dict) or ci.get("status") != "passed" or ci.get("commit") != candidate:
                raise AgentEnvError(f"{gate} approval requires passing CI for the candidate commit")
            context.update({"git_sha": candidate, "ci": ci, "pull_request": status.get("pull_request")})
            if gate == "hardware":
                context["physical_hardware"] = self.manifest["promotion"]["physical_hardware"]
        else:
            raise AgentEnvError("gate must be plan, merge, or hardware")
        return sha256_json(context), context

    def approval_count(self, gate: str) -> int:
        path = self.approvals_path / gate
        if not path.is_dir():
            return 0
        digest, _ = self._approval_context(gate)
        return sum(1 for p in path.glob("*.json") if load_json(p).get("context_sha256") == digest)

    def _archive_stale_approval(self, source: Path, gate: str) -> None:
        stamp = utc_now().replace(":", "").replace("+00:00", "Z")
        destination = self.path / "approval-history" / stamp / gate / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), destination)

    def invalidate_gates(self, gates: set[str], *, event: str) -> None:
        status = self.status
        epochs = dict(status.get("gate_epochs", {}))
        for gate in gates:
            epochs[gate] = int(epochs.get(gate, 0)) + 1
        self.update_status({"gate_epochs": epochs}, event=event)

    def add_approval(self, gate: str, actor: str | None = None, note: str = "") -> tuple[int, int]:
        gate = gate.lower()
        allowed = {"plan": {"PLANNED"}, "merge": {"CI_VERIFIED"}, "hardware": {"CI_VERIFIED", "MERGE_APPROVED"}}
        if gate not in allowed:
            raise AgentEnvError("gate must be plan, merge, or hardware")
        status = self.status
        if status["state"] not in allowed[gate]:
            raise AgentEnvError(f"gate '{gate}' cannot be approved while state is {status['state']}")
        threshold = {"plan": int(self.policy["plan_approvals"]), "merge": int(self.policy["merge_approvals"]), "hardware": int(self.policy["hardware_approvals"])}[gate]
        if gate == "hardware" and threshold == 0:
            raise AgentEnvError("hardware approval is not applicable to this risk class")
        identity = safe_actor(actor)
        digest, context = self._approval_context(gate)
        gate_dir = self.approvals_path / gate
        gate_dir.mkdir(parents=True, exist_ok=True)
        target = gate_dir / f"{identity}.json"
        if target.exists():
            existing = load_json(target)
            if existing.get("context_sha256") == digest:
                raise AgentEnvError(f"{identity} already approved the current '{gate}' gate context")
            self._archive_stale_approval(target, gate)
        atomic_write_json(target, {
            "schema_version": 1, "work_item": self.work_id, "gate": gate, "actor": identity,
            "timestamp": utc_now(), "note": note, "state": status["state"],
            "context_sha256": digest, "context": context,
        })
        count = self.approval_count(gate)
        self._append_trace("human_approval_recorded", status["state"], status["state"], {"gate": gate, "count": count, "required": threshold}, actor=identity)
        if count >= threshold and gate == "plan":
            self.transition("PLANNED", "PLAN_APPROVED", event="plan_gate_satisfied")
        elif count >= threshold and gate == "merge":
            self.transition("CI_VERIFIED", "MERGE_APPROVED", event="merge_gate_satisfied")
        self.refresh_evidence_index()
        return count, threshold

    def set_pull_request(self, data: dict[str, Any]) -> None:
        candidate = self.require_publishable_candidate()
        if data.get("head_sha") != candidate:
            raise AgentEnvError(f"remote pull request head {data.get('head_sha')} does not match candidate {candidate}")
        self.update_status({"pull_request": data, "merge": None}, event="pull_request_recorded")

    def record_ci(self, status_value: str, url: str, commit: str | None = None) -> None:
        value = status_value.lower()
        if value not in {"passed", "failed"}:
            raise AgentEnvError("CI status must be passed or failed")
        current = self.status["state"]
        if current not in {"PR_OPEN", "PR_READY", "CI_VERIFIED", "BLOCKED"}:
            raise AgentEnvError(f"cannot record CI while state is {current}")
        candidate = self.candidate_sha() or git_sha(self.repo)
        recorded = commit or candidate
        if recorded != candidate:
            raise AgentEnvError(f"CI commit {recorded} does not match current candidate {candidate}")
        pr = self.status.get("pull_request")
        if current == "PR_OPEN" and (not isinstance(pr, dict) or pr.get("head_sha") != recorded):
            raise AgentEnvError("CI commit does not match the recorded open pull-request head SHA")
        self.invalidate_gates({"merge", "hardware"}, event="ci_context_changed")
        self.update_status({"ci": {"status": value, "url": url, "commit": recorded, "recorded_at": utc_now()}, "merge": None}, event="ci_result_recorded")
        current = self.status["state"]
        if value == "passed" and current != "CI_VERIFIED":
            self.transition({"PR_OPEN", "PR_READY", "BLOCKED"}, "CI_VERIFIED", event="ci_gate_satisfied")
        elif value == "failed" and current != "BLOCKED":
            self.transition({"PR_OPEN", "PR_READY", "CI_VERIFIED"}, "BLOCKED", event="ci_gate_failed", error="CI failed")

    def invalidate_execution(self, route: str) -> str:
        """Invalidate current bindings at the selected diagnosis recovery boundary."""
        status = self.status
        if status["state"] != "DIAGNOSED":
            raise AgentEnvError(f"diagnosis routing requires DIAGNOSED, current state is {status['state']}")
        implementation = dict(status.get("implementation") or {}) if isinstance(status.get("implementation"), dict) else None
        updates: dict[str, Any] = {"pull_request": None, "ci": None, "merge": None, "last_error": None}
        target: str
        if route == "implementation":
            updates["implementation"] = None
            target = "PLAN_APPROVED"
            self.invalidate_gates({"merge", "hardware"}, event="implementation_retry_invalidated_downstream")
        elif route == "local-test":
            if not implementation or not implementation.get("candidate_sha"):
                raise AgentEnvError("local-test route requires an existing candidate")
            implementation["local_test_sha"] = None
            implementation["integration_test_sha"] = None
            implementation["reviewed_sha"] = None
            updates["implementation"] = implementation
            target = "IMPLEMENTED"
            self.invalidate_gates({"merge", "hardware"}, event="local_retry_invalidated_downstream")
        elif route == "environment":
            if not implementation or not implementation.get("candidate_sha") or not implementation.get("local_test_sha"):
                raise AgentEnvError("environment route requires a locally verified candidate")
            implementation["integration_test_sha"] = None
            implementation["reviewed_sha"] = None
            updates["implementation"] = implementation
            target = "LOCALLY_VERIFIED"
            self.invalidate_gates({"merge", "hardware"}, event="environment_retry_invalidated_downstream")
        elif route == "plan":
            updates.update({"current_plan": None, "implementation": None})
            target = "INTAKE"
            self.invalidate_gates({"plan", "merge", "hardware"}, event="plan_retry_invalidated_all")
        elif route == "blocked":
            return self.transition("DIAGNOSED", "BLOCKED", event="diagnosis_routed_blocked")["state"]
        else:
            raise AgentEnvError(f"unknown diagnosis route: {route}")
        self.update_status(updates, event=f"diagnosis_route_{route}_invalidated_bindings")
        return self.transition("DIAGNOSED", target, event=f"diagnosis_routed_{route}")["state"]

    def record_promotion(self, level: str, evidence: str, actor: str | None = None) -> None:
        if self.status["state"] != "MERGE_APPROVED":
            raise AgentEnvError("promotion requires MERGE_APPROVED state")
        level = level.lower()
        if level not in {"simulation", "hil", "physical"}:
            raise AgentEnvError("promotion level must be simulation, hil, or physical")
        if level in {"hil", "physical"}:
            if self.manifest["promotion"]["physical_hardware"] != "human-approved":
                raise AgentEnvError("physical/HIL promotion is prohibited by the manifest")
            required = int(self.policy["hardware_approvals"])
            if self.approval_count("hardware") < required:
                raise AgentEnvError(f"physical/HIL promotion requires {required} distinct hardware approvals")

        # Promotion is a post-merge operation. Reconcile with the configured SCM
        # provider at the point of promotion and fail closed if the PR is merely
        # approved/open, if its head changed, or if merge proof is unavailable.
        from .scm import verify_pull_request_merged

        candidate = self.require_publishable_candidate()
        ci = self.status.get("ci")
        if not isinstance(ci, dict) or ci.get("status") != "passed" or ci.get("commit") != candidate:
            raise AgentEnvError("promotion requires passing CI for the reviewed candidate")
        merge = verify_pull_request_merged(self)
        if merge.get("head_sha") != candidate:
            raise AgentEnvError("remote merge proof does not match the reviewed candidate")
        self.write_artifact("merge-verification.json", json.dumps(merge, indent=2, sort_keys=True))

        identity = safe_actor(actor)
        self.update_status({
            "merge": merge,
            "promotion": {
                "level": level, "evidence": evidence, "actor": identity,
                "timestamp": utc_now(), "git_sha": candidate, "merge_sha": merge["merge_sha"],
            },
        }, event="remote_merge_verified_and_promotion_recorded")
        self.transition("MERGE_APPROVED", "PROMOTED", event="promotion_gate_satisfied")

    def close(self, actor: str | None = None, note: str = "") -> None:
        if self.status["state"] != "PROMOTED":
            raise AgentEnvError("work item can close only after promotion")
        identity = safe_actor(actor)
        self.write_artifact("closure.md", f"# Closure\n\nActor: {identity}\n\n{note}")
        self.transition("PROMOTED", "CLOSED", event="work_item_closed")

    def recover(self, target: str, actor: str | None = None, note: str = "") -> None:
        allowed = {"INTAKE", "PLANNED", "PLAN_APPROVED", "IMPLEMENTED", "LOCALLY_VERIFIED", "ENV_VERIFIED", "REVIEWED", "DIAGNOSING"}
        if target not in allowed:
            raise AgentEnvError(f"recovery target is not allowed: {target}")
        current = self.status["state"]
        if current not in TRANSIENT_STATES | {"BLOCKED", "DIAGNOSED"}:
            raise AgentEnvError(f"recovery is not allowed from state {current}")
        identity = safe_actor(actor)
        self._append_trace("manual_recovery_requested", current, target, {"note": note}, actor=identity)
        self.transition(current, target, event="manual_recovery_applied")

    def refresh_evidence_index(self) -> None:
        if not self.path.exists():
            return
        files: list[dict[str, Any]] = []
        for path in sorted(self.path.rglob("*")):
            if not path.is_file() or path in {self.lock_path, self.evidence_index_path}:
                continue
            files.append({"path": str(path.relative_to(self.path)), "size": path.stat().st_size, "sha256": sha256_file(path)})
        atomic_write_json(self.evidence_index_path, {"schema_version": 1, "work_item": self.work_id, "generated_at": utc_now(), "files": files})


def _path_matches(path: str, pattern: str) -> bool:
    path = path.lstrip("./")
    pattern = pattern.lstrip("./")
    if pattern in {"*", "**", "**/*"}:
        return True
    if path == pattern:
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pattern)
