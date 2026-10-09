"""Transactional immutable records, object storage, validity and archived history.

The ledger is the authority; exports are projections. Record content never changes.
Archive compaction replaces inline bytes with a verified, indexed pack reference.
"""

from __future__ import annotations

from contextlib import contextmanager
import gzip
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator

from .common import (
    Conflict,
    FrameworkError,
    IntegrityError,
    atomic_write,
    bytes_digest,
    canonical,
    decode,
    digest,
    identifier,
    now,
)

RELATIONS = frozenset(
    {
        "derived_from",
        "implements",
        "verifies",
        "constrains",
        "executes_on",
        "materialized_from",
        "generated_from",
        "approved_as_part_of",
    }
)
OWNERS = frozenset(
    {
        "framework",
        "human",
        "planner",
        "coder",
        "tester",
        "reviewer",
        "safety_reviewer",
        "debugger",
    }
)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.objects = self.root / "objects"
        self.objects.mkdir(exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(
            self.root / "ledger.sqlite3", timeout=30, isolation_level=None
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT OR IGNORE INTO metadata VALUES('schema_version','1');
            CREATE TABLE IF NOT EXISTS records(
                id TEXT NOT NULL, revision INTEGER NOT NULL, kind TEXT NOT NULL,
                owner TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
                data BLOB, pack TEXT, position INTEGER, PRIMARY KEY(id,revision));
            CREATE TABLE IF NOT EXISTS heads(
                id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL,
                cause TEXT, FOREIGN KEY(id,revision) REFERENCES records(id,revision));
            CREATE TABLE IF NOT EXISTS edges(
                upstream TEXT NOT NULL, downstream TEXT NOT NULL, relation TEXT NOT NULL,
                basis_revision INTEGER NOT NULL,
                PRIMARY KEY(upstream,downstream,relation),
                FOREIGN KEY(upstream) REFERENCES heads(id),
                FOREIGN KEY(downstream) REFERENCES heads(id));
            CREATE INDEX IF NOT EXISTS edges_down ON edges(downstream);
            CREATE INDEX IF NOT EXISTS records_kind ON records(kind,id,revision);
            CREATE INDEX IF NOT EXISTS records_pack ON records(pack);
            CREATE INDEX IF NOT EXISTS records_inline ON records(id,revision) WHERE data IS NOT NULL;
            CREATE TABLE IF NOT EXISTS events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                previous TEXT NOT NULL, digest TEXT NOT NULL, data BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS baselines(
                id TEXT PRIMARY KEY, digest TEXT NOT NULL, data BLOB NOT NULL);
        """
        )
        if (
            self.db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            != "1"
        ):
            raise FrameworkError(
                "unsupported ledger version; explicit migration required"
            )

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        nested = self.db.in_transaction
        if nested:
            self.db.execute("SAVEPOINT nested_write")
        else:
            self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("RELEASE nested_write" if nested else "COMMIT")
        except BaseException:
            if nested:
                self.db.execute("ROLLBACK TO nested_write")
                self.db.execute("RELEASE nested_write")
            else:
                self.db.execute("ROLLBACK")
            raise

    def event(self, kind: str, payload: Any) -> str:
        if not self.db.in_transaction:
            with self.transaction():
                return self.event(kind, payload)
        row = self.db.execute(
            "SELECT digest FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous = row[0] if row else "0" * 64
        data = canonical({"event": kind, "at": now(), "payload": payload})
        hashed = bytes_digest(previous.encode() + b"\n" + data)
        self.db.execute(
            "INSERT INTO events(previous,digest,data) VALUES(?,?,?)",
            (previous, hashed, data),
        )
        return hashed

    def blob(self, data: bytes) -> str:
        hashed = bytes_digest(data)
        path = self.objects / hashed[:2] / hashed[2:]
        if path.exists():
            if bytes_digest(path.read_bytes()) != hashed:
                raise IntegrityError("content-addressed object is corrupted")
        else:
            atomic_write(path, data)
        return hashed

    def read_blob(self, hashed: str) -> bytes:
        if len(hashed) != 64 or any(c not in "0123456789abcdef" for c in hashed):
            raise FrameworkError("invalid object digest")
        try:
            data = (self.objects / hashed[:2] / hashed[2:]).read_bytes()
        except OSError as exc:
            raise IntegrityError(f"object unavailable: {hashed}") from exc
        if bytes_digest(data) != hashed:
            raise IntegrityError(f"object digest mismatch: {hashed}")
        return data

    def head(self, artifact_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT h.*,r.kind,r.owner,r.digest FROM heads h JOIN records r USING(id,revision) WHERE id=?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise FrameworkError(f"unknown artifact: {artifact_id}")
        return dict(row)

    def exists(self, artifact_id: str) -> bool:
        return (
            self.db.execute("SELECT 1 FROM heads WHERE id=?", (artifact_id,)).fetchone()
            is not None
        )

    def ref(self, artifact_id: str) -> dict[str, Any]:
        h = self.head(artifact_id)
        return {k: h[k] for k in ("id", "revision", "digest")}

    def get(self, artifact_id: str, revision: int | None = None) -> dict[str, Any]:
        if revision is None:
            revision = self.head(artifact_id)["revision"]
        row = self.db.execute(
            "SELECT * FROM records WHERE id=? AND revision=?", (artifact_id, revision)
        ).fetchone()
        if row is None:
            raise FrameworkError(f"unknown revision: {artifact_id}@{revision}")
        data = row["data"]
        if data is None:
            try:
                packed = gzip.decompress(self.read_blob(row["pack"]))
                lines = packed.splitlines()
                data = lines[row["position"]]
            except (OSError, EOFError, IndexError, TypeError) as exc:
                raise IntegrityError("invalid graph archive") from exc
        if bytes_digest(data) != row["digest"]:
            raise IntegrityError(f"record content changed: {artifact_id}@{revision}")
        record = decode(data)
        if (
            record["id"] != artifact_id
            or record["revision"] != revision
            or record["kind"] != row["kind"]
            or record["owner"] != row["owner"]
        ):
            raise IntegrityError("archive locator identity mismatch")
        return record

    def resolve(
        self, reference: dict[str, Any], *, current: bool = False
    ) -> dict[str, Any]:
        record = self.get(reference["id"], reference["revision"])
        if digest(record) != reference["digest"]:
            raise IntegrityError("reference digest mismatch")
        if current:
            h = self.head(reference["id"])
            if h["revision"] != reference["revision"] or h["state"] != "CURRENT":
                raise Conflict(f"artifact is not current: {reference['id']}")
        return record

    def list(
        self,
        kind: str | None = None,
        state: str | None = None,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        sql = "SELECT h.*,r.kind,r.owner,r.digest FROM heads h JOIN records r USING(id,revision) WHERE 1=1"
        params: list[Any] = []
        if not include_archived:
            sql += " AND h.state<>'SUPERSEDED'"
        if kind:
            sql += " AND r.kind=?"
            params.append(kind)
        if state:
            sql += " AND h.state=?"
            params.append(state)
        return [dict(x) for x in self.db.execute(sql + " ORDER BY h.id", params)]

    def _cycle_check(self, artifact_id: str, upstreams: list[str]) -> None:
        for source in upstreams:
            if source == artifact_id:
                raise FrameworkError("dependency self-cycle")
            row = self.db.execute(
                """WITH RECURSIVE reach(id) AS (
                SELECT downstream FROM edges WHERE upstream=?
                UNION SELECT e.downstream FROM edges e JOIN reach r ON e.upstream=r.id)
                SELECT 1 FROM reach WHERE id=? LIMIT 1""",
                (artifact_id, source),
            ).fetchone()
            if row:
                raise FrameworkError(f"dependency cycle: {source} -> {artifact_id}")

    def publish(
        self,
        artifact_id: str,
        kind: str,
        owner: str,
        payload: Any,
        dependencies: Iterable[tuple[str, str]] = (),
        *,
        expected_revision: int = 0,
    ) -> dict[str, Any]:
        """Controller-managed ID/revision write; role outputs never call this directly."""
        identifier(artifact_id)
        if (
            owner not in OWNERS
            or not kind
            or not isinstance(kind, str)
            or type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise FrameworkError("invalid artifact owner or kind")
        deps = list(dependencies)
        if len(set(deps)) != len(deps) or any(rel not in RELATIONS for _, rel in deps):
            raise FrameworkError("duplicate or invalid dependency relation")
        with self.transaction():
            old = self.head(artifact_id) if self.exists(artifact_id) else None
            if (old["revision"] if old else 0) != expected_revision:
                raise Conflict(f"revision changed: {artifact_id}")
            if old and old["state"] == "SUPERSEDED":
                raise FrameworkError("retired stable identities cannot be reused")
            if old and (old["kind"] != kind or old["owner"] != owner):
                raise FrameworkError(
                    "stable identity cannot be reused for a different kind/owner"
                )
            basis = []
            for upstream, relation in sorted(deps):
                h = self.head(upstream)
                if h["state"] != "CURRENT":
                    raise Conflict(f"dependency is not current: {upstream}")
                basis.append({"reference": self.ref(upstream), "relation": relation})
            self._cycle_check(artifact_id, [x[0] for x in deps])
            revision = expected_revision + 1
            record = {
                "encoder_version": 1,
                "id": artifact_id,
                "revision": revision,
                "kind": kind,
                "owner": owner,
                "payload": payload,
                "dependencies": basis,
                "created_at": now(),
            }
            raw = canonical(record)
            hashed = bytes_digest(raw)
            if old:
                self.invalidate([artifact_id], include_roots=False)
            self.db.execute(
                "INSERT INTO records(id,revision,kind,owner,digest,data) VALUES(?,?,?,?,?,?)",
                (artifact_id, revision, kind, owner, hashed, raw),
            )
            self.db.execute(
                "INSERT INTO heads VALUES(?,?,'CURRENT',NULL) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,state='CURRENT',cause=NULL",
                (artifact_id, revision),
            )
            self.db.execute("DELETE FROM edges WHERE downstream=?", (artifact_id,))
            self.db.executemany(
                "INSERT INTO edges VALUES(?,?,?,?)",
                [
                    (
                        b["reference"]["id"],
                        artifact_id,
                        b["relation"],
                        b["reference"]["revision"],
                    )
                    for b in basis
                ],
            )
            self.event(
                "artifact_revision",
                {
                    "id": artifact_id,
                    "revision": revision,
                    "digest": hashed,
                    "dependencies": [x["reference"]["id"] for x in basis],
                },
            )
            return {"id": artifact_id, "revision": revision, "digest": hashed}

    def descendants(
        self, roots: Iterable[str], *, include_roots: bool = False
    ) -> list[str]:
        roots = sorted(set(roots))
        if not roots:
            return []
        self.db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS query_roots(id TEXT PRIMARY KEY)"
        )
        self.db.execute("DELETE FROM query_roots")
        self.db.executemany("INSERT INTO query_roots VALUES(?)", [(x,) for x in roots])
        rows = self.db.execute(
            """WITH RECURSIVE reach(id) AS (
            SELECT id FROM query_roots UNION
            SELECT e.downstream FROM edges e JOIN reach r ON e.upstream=r.id)
            SELECT id FROM reach ORDER BY id"""
        ).fetchall()
        excluded = set() if include_roots else set(roots)
        return [r[0] for r in rows if r[0] not in excluded]

    def invalidate(
        self, roots: Iterable[str], *, include_roots: bool = True
    ) -> list[str]:
        roots = list(roots)
        with self.transaction():
            for root in roots:
                if self.head(root)["state"] == "SUPERSEDED":
                    raise FrameworkError(
                        "retired identities cannot be invalidated as alive artifacts"
                    )
            affected = self.descendants(roots, include_roots=include_roots)
            cause = ",".join(sorted(roots))
            self.db.executemany(
                "UPDATE heads SET state='STALE',cause=? WHERE id=? AND state='CURRENT'",
                [(cause, x) for x in affected],
            )
            if affected:
                self.event(
                    "validity_changed",
                    {
                        "roots": roots,
                        "affected_count": len(affected),
                        "include_roots": include_roots,
                    },
                )
            return affected

    def retire(self, artifact_id: str, *, reason: str) -> None:
        """Retire only an explicitly obsolete leaf; never merge live causal identities."""
        if not reason.strip():
            raise FrameworkError("retirement needs a lineage/reason")
        with self.transaction():
            self.head(artifact_id)
            if self.db.execute(
                "SELECT 1 FROM edges WHERE upstream=?", (artifact_id,)
            ).fetchone():
                raise Conflict("live dependents still require this identity")
            self.db.execute(
                "UPDATE heads SET state='SUPERSEDED',cause=? WHERE id=?",
                (reason, artifact_id),
            )
            self.db.execute("DELETE FROM edges WHERE downstream=?", (artifact_id,))
            self.event("artifact_retired", {"id": artifact_id, "reason": reason})

    def revalidate(
        self, artifact_id: str, *, owner: str, expected_revision: int
    ) -> dict[str, Any]:
        record = self.get(artifact_id, expected_revision)
        if record["owner"] != owner:
            raise FrameworkError("only the artifact owner may reevaluate it")
        deps = [(x["reference"]["id"], x["relation"]) for x in record["dependencies"]]
        return self.publish(
            artifact_id,
            record["kind"],
            owner,
            record["payload"],
            deps,
            expected_revision=expected_revision,
        )

    def check_integrity(self) -> dict[str, Any]:
        previous = "0" * 64
        count = 0
        projection = {}
        graph = {}
        for row in self.db.execute("SELECT * FROM events ORDER BY sequence"):
            if (
                row["previous"] != previous
                or bytes_digest(previous.encode() + b"\n" + row["data"])
                != row["digest"]
            ):
                raise IntegrityError("event hash chain mismatch")
            previous = row["digest"]
            count += 1
            event = decode(row["data"])
            value = event["payload"]
            if event["event"] == "artifact_revision":
                recorded = self.db.execute(
                    "SELECT digest FROM records WHERE id=? AND revision=?",
                    (value["id"], value["revision"]),
                ).fetchone()
                if recorded is None or recorded[0] != value["digest"]:
                    raise IntegrityError("journal record digest mismatch")
                projection[value["id"]] = (value["revision"], "CURRENT")
                graph[value["id"]] = set(value["dependencies"])
            elif event["event"] == "validity_changed":
                reachable = set(value["roots"])
                children = {}
                for child, parents in graph.items():
                    for parent in parents:
                        children.setdefault(parent, []).append(child)
                pending = list(reachable)
                while pending:
                    for child in children.get(pending.pop(), []):
                        if child not in reachable:
                            reachable.add(child)
                            pending.append(child)
                if not value["include_roots"]:
                    reachable -= set(value["roots"])
                for key in reachable:
                    if key in projection:
                        projection[key] = (projection[key][0], "STALE")
            elif event["event"] == "artifact_retired":
                projection[value["id"]] = (projection[value["id"]][0], "SUPERSEDED")
                graph[value["id"]] = set()
        actual_projection = {
            h["id"]: (h["revision"], h["state"])
            for h in self.list(include_archived=True)
        }
        if actual_projection != projection:
            raise IntegrityError(
                "head/validity projection differs from the immutable journal"
            )
        # Stream each history pack once; do not repeatedly decompress each record.
        packed = None
        lines = []
        for row in self.db.execute(
            "SELECT * FROM records ORDER BY pack,position,id,revision"
        ):
            data = row["data"]
            if data is None:
                if packed != row["pack"]:
                    packed = row["pack"]
                    lines = gzip.decompress(self.read_blob(packed)).splitlines()
                try:
                    data = lines[row["position"]]
                except (IndexError, TypeError) as exc:
                    raise IntegrityError("invalid history pack locator") from exc
            if bytes_digest(data) != row["digest"]:
                raise IntegrityError("history content digest mismatch")
            value = decode(data)
            if any(value[k] != row[k] for k in ("id", "revision", "kind", "owner")):
                raise IntegrityError("history locator metadata mismatch")
        # The current edge projection must match immutable head dependencies.
        for h in self.list():
            record = self.get(h["id"], h["revision"])
            expected = {
                (x["reference"]["id"], x["relation"], x["reference"]["revision"])
                for x in record["dependencies"]
            }
            actual = {
                tuple(x)
                for x in self.db.execute(
                    "SELECT upstream,relation,basis_revision FROM edges WHERE downstream=?",
                    (h["id"],),
                )
            }
            if expected != actual:
                raise IntegrityError(f"dependency projection mismatch: {h['id']}")
        return {
            "records": self.db.execute("SELECT count(*) FROM records").fetchone()[0],
            "events": count,
            "event_root": previous,
        }

    def baseline(
        self, baseline_id: str, label: str, *, compact: bool = False
    ) -> dict[str, Any]:
        identifier(baseline_id)
        with self.transaction():
            if self.db.execute(
                "SELECT 1 FROM baselines WHERE id=?", (baseline_id,)
            ).fetchone():
                raise Conflict("baseline identity already exists")
            for row in self.list("work"):
                if self.get(row["id"])["payload"].get("state") not in {
                    "PROMOTED",
                    "CLOSED",
                }:
                    raise Conflict(
                        "baseline requires a stable state; unresolved work remains"
                    )
            heads = self.list()
            if any(x["state"] != "CURRENT" for x in heads):
                raise Conflict("baseline requires current alive artifacts")
            refs = [{k: h[k] for k in ("id", "revision", "digest")} for h in heads]
            record = {
                "id": baseline_id,
                "label": label,
                "created_at": now(),
                "heads": refs,
                "root": digest(refs),
            }
            raw = canonical(record)
            hashed = bytes_digest(raw)
            self.db.execute(
                "INSERT INTO baselines VALUES(?,?,?)", (baseline_id, hashed, raw)
            )
            self.event("baseline_created", {"id": baseline_id, "digest": hashed})
        if compact:
            record["compaction"] = self.compact()
        return record

    def get_baseline(self, baseline_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM baselines WHERE id=?", (baseline_id,)
        ).fetchone()
        if row is None:
            raise FrameworkError("unknown baseline")
        if bytes_digest(row["data"]) != row["digest"]:
            raise IntegrityError("baseline content changed")
        record = decode(row["data"])
        if digest(record["heads"]) != record["root"]:
            raise IntegrityError("baseline frontier digest mismatch")
        return record

    def history(self, baseline_id: str) -> list[dict[str, Any]]:
        return [self.resolve(ref) for ref in self.get_baseline(baseline_id)["heads"]]

    def compact(self, batch_size: int = 2048) -> dict[str, int]:
        if batch_size < 1 or batch_size > 10000:
            raise FrameworkError("archive batch must contain 1..10000 records")
        with self.transaction():
            if not self.db.execute("SELECT 1 FROM baselines LIMIT 1").fetchone():
                raise Conflict("create a stable baseline before compaction")
            if any(
                self.get(h["id"])["payload"].get("state") not in {"PROMOTED", "CLOSED"}
                for h in self.list("work")
            ):
                raise Conflict("cannot compact unresolved work")
            count = 0
            packs = 0
            while True:
                rows = self.db.execute(
                    """SELECT r.* FROM records r JOIN heads h ON r.id=h.id
                    WHERE r.revision<h.revision AND r.data IS NOT NULL ORDER BY r.id,r.revision LIMIT ?""",
                    (batch_size,),
                ).fetchall()
                if not rows:
                    break
                for row in rows:
                    if bytes_digest(row["data"]) != row["digest"]:
                        raise IntegrityError("refusing to archive corrupted history")
                raw = b"\n".join(row["data"] for row in rows) + b"\n"
                packed = gzip.compress(raw, compresslevel=6, mtime=0)
                hashed = self.blob(packed)
                if gzip.decompress(self.read_blob(hashed)) != raw:
                    raise IntegrityError("archive verification failed")
                self.db.executemany(
                    "UPDATE records SET data=NULL,pack=?,position=? WHERE id=? AND revision=?",
                    [
                        (hashed, i, row["id"], row["revision"])
                        for i, row in enumerate(rows)
                    ],
                )
                count += len(rows)
                packs += 1
            self.event("history_compacted", {"records": count, "packs": packs})
        self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        return {"archived_records": count, "packs": packs}
