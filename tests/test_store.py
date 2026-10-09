import gzip
import multiprocessing

import pytest

from agent_framework.common import (
    Conflict,
    FrameworkError,
    IntegrityError,
    decode,
    digest,
)
from agent_framework.graph import graph_data, mermaid, svg, topological
from agent_framework.store import Store


def _concurrent_writer(root, barrier, result):
    with Store(root) as s:
        barrier.wait(timeout=5)
        try:
            s.publish(
                "SHARED",
                "document",
                "planner",
                {"pid": __import__("os").getpid()},
                expected_revision=1,
            )
            result.put("committed")
        except Conflict:
            result.put("conflict")


def test_concurrent_writers_cannot_overwrite_the_same_revision(tmp_path):
    with Store(tmp_path) as s:
        s.publish("SHARED", "document", "planner", {})
    ctx = multiprocessing.get_context("fork")
    barrier, result = ctx.Barrier(2), ctx.Queue()
    processes = [
        ctx.Process(target=_concurrent_writer, args=(tmp_path, barrier, result))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    outcomes = sorted(result.get(timeout=10) for _ in processes)
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0
    assert outcomes == ["committed", "conflict"]
    with Store(tmp_path) as s:
        assert s.head("SHARED")["revision"] == 2
        assert s.check_integrity()["records"] == 2


def test_historical_failure_view_uses_baseline_revision(tmp_path):
    with Store(tmp_path) as s:
        s.publish(
            "RESULT",
            "verification_result",
            "framework",
            {"result": {"status": "candidate_failed", "candidate_evaluated": True}},
        )
        s.baseline("BASE-FAILED", "failed historical evidence")
        s.publish(
            "RESULT",
            "verification_result",
            "framework",
            {"result": {"status": "passed", "candidate_evaluated": True}},
            expected_revision=1,
        )
        assert graph_data(s, view="failure")["nodes"] == []
        historical = graph_data(s, view="failure", baseline="BASE-FAILED")
        assert historical["nodes"][0]["state"] == "FAILED"


def test_revision_cas_and_immutable_history(tmp_path):
    with Store(tmp_path) as s:
        old = s.publish("REQ-001", "requirement", "planner", {"text": "before"})
        s.publish("CMP-001", "component", "planner", {}, [("REQ-001", "derived_from")])
        s.publish(
            "REQ-001", "requirement", "planner", {"text": "after"}, expected_revision=1
        )
        assert s.resolve(old)["payload"]["text"] == "before"
        assert s.head("CMP-001")["state"] == "STALE"
        with pytest.raises(Conflict):
            s.publish("REQ-001", "requirement", "planner", {}, expected_revision=1)
        with pytest.raises(FrameworkError):
            s.revalidate("CMP-001", owner="coder", expected_revision=1)
        s.revalidate("CMP-001", owner="planner", expected_revision=1)
        assert s.check_integrity()["records"] == 4


def test_diamond_invalidation_is_complete_but_not_unrelated(tmp_path):
    with Store(tmp_path) as s:
        for key, deps in [
            ("AA", []),
            ("BB", ["AA"]),
            ("CC", ["AA"]),
            ("DD", ["BB", "CC"]),
            ("EE", []),
        ]:
            s.publish(key, "test", "framework", {}, [(d, "derived_from") for d in deps])
        assert s.invalidate(["AA"]) == ["AA", "BB", "CC", "DD"]
        assert s.head("EE")["state"] == "CURRENT"


def test_cycle_rejected_transactionally(tmp_path):
    with Store(tmp_path) as s:
        s.publish("AA", "test", "framework", {})
        s.publish("BB", "test", "framework", {}, [("AA", "derived_from")])
        with pytest.raises(FrameworkError, match="cycle"):
            s.publish(
                "AA",
                "test",
                "framework",
                {},
                [("BB", "derived_from")],
                expected_revision=1,
            )
        assert s.head("AA")["revision"] == 1


def test_baseline_compaction_keeps_live_identities_edges_and_lazy_history(tmp_path):
    with Store(tmp_path) as s:
        for rev in range(8):
            s.publish("AA", "test", "framework", {"v": rev}, expected_revision=rev)
        s.publish("BB", "test", "framework", {}, [("AA", "derived_from")])
        s.baseline("BASE-ONE", "stable")
        result = s.compact(batch_size=2)
        assert result == {"archived_records": 7, "packs": 4}
        assert s.get("AA", 1)["payload"] == {"v": 0}
        assert len(s.list()) == 2 and s.descendants(["AA"]) == ["BB"]
        assert s.history("BASE-ONE")[0]["revision"] == 8
        assert s.check_integrity()["records"] == 9
        assert s.compact()["archived_records"] == 0


def test_corrupt_history_is_detected_before_compaction(tmp_path):
    with Store(tmp_path) as s:
        s.publish("AA", "test", "framework", {})
        s.publish("AA", "test", "framework", {}, expected_revision=1)
        s.baseline("BASE-ONE", "stable")
        s.db.execute("UPDATE records SET data=? WHERE revision=1", (b"{}",))
        with pytest.raises(IntegrityError):
            s.compact()


def test_event_and_cas_integrity(tmp_path):
    with Store(tmp_path) as s:
        s.publish("AA", "test", "framework", {})
        blob = s.blob(b"evidence")
        path = s.objects / blob[:2] / blob[2:]
        path.write_bytes(b"tampered")
        with pytest.raises(IntegrityError):
            s.read_blob(blob)
        s.db.execute("UPDATE events SET data=?", (b"changed",))
        with pytest.raises(IntegrityError):
            s.check_integrity()


def test_focused_graph_labels_and_edges_are_escaped(tmp_path):
    with Store(tmp_path) as s:
        s.publish("AA", "requirement", "planner", {"text": "<script>bad</script>"})
        s.publish("BB", "component", "planner", {}, [("AA", "derived_from")])
        value = graph_data(s, focus="AA", limit=1)
        assert value["shown"] == 1 and value["omitted"] == 1
        assert "<svg" in svg(value) and "<script>" not in svg(value)
        assert "flowchart" in mermaid(value)
        with pytest.raises(FrameworkError):
            topological(["AA", "BB"], [("AA", "BB"), ("BB", "AA")])


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_noncanonical_inputs_are_rejected(raw):
    with pytest.raises(FrameworkError):
        decode(raw)
