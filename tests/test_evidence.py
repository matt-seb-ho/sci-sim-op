"""Tests for the layered evidence corpus, trajectory mining, and EFC.

Every fixture is built inline. Nothing here may touch a ``/data`` volume: the
whole point of the rebuild is that the loop is testable without one, and a test
that silently skips when a mount is absent is how v1's missing reward signal
survived three rounds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_evolve.evidence.corpus import CorpusConfig, RoundEvidence, build_evidence
from harness_evolve.evidence.diagnostics import (
    MiningConfig,
    diagnosis_from_tree,
    extract_entities,
    mine_trajectory,
    per_section,
    trajectory_excerpt,
    worst_subtrees,
)
from harness_evolve.evidence.efc import EFCConfig, efc, efc_report
from harness_evolve.simulators.base import Diagnosis
from harness_evolve.types import Cost, Rollout, Score


# --------------------------------------------------------------------------
# fixture builders
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _subdirs(tmp_path):
    """Scratch subdirectories, so one test can build several distinct streams."""
    for sub in ("a", "b", "c", "d"):
        (tmp_path / sub).mkdir(exist_ok=True)


def tool_use(name: str, tid: str, **args) -> dict:
    return {"type": "tool_use", "name": name, "id": tid, "input": args}


def assistant(*blocks: dict) -> dict:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def user(*blocks: dict) -> dict:
    return {"type": "user", "message": {"content": list(blocks)}}


def tool_result(tid: str, text: str, is_error: bool = False) -> dict:
    return {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": is_error}


def text(body: str) -> dict:
    return {"type": "text", "text": body}


def thinking(body: str) -> dict:
    return {"type": "thinking", "thinking": body}


def write_stream(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


def rollout(
    task: str,
    value: float,
    *,
    seed: int = 1,
    status: str = "success",
    candidate_id: str = "c1",
    events_path: str | None = None,
    validator_events: list[dict] | None = None,
    cost: Cost | None = None,
    error: str | None = None,
    artifacts_dir: str | None = None,
) -> Rollout:
    return Rollout(
        task=task,
        candidate_id=candidate_id,
        seed=seed,
        score=Score(task=task, value=value, status=status),
        cost=cost or Cost(tool_calls=20, wall_seconds=600, output_tokens=4000, usd=0.5),
        artifacts_dir=artifacts_dir,
        events_path=events_path,
        validator_events=validator_events or [],
        error=error,
    )


UNKNOWN_ATTR = (
    "Error: unknown attribute 'logLevl' on element <SinglePhaseFVM> in wellbore.xml. "
    "Valid attributes are: logLevel, name, targetRegions, discretization."
)


def erroring_trajectory(path: Path, n_errors: int = 1, *, ignore: bool = False) -> Path:
    """Agent edits, is told about a named attribute, and edits again.

    ``ignore=True`` makes every post-feedback action byte-identical to the one
    before it, which is the retention-zero case.
    """
    events: list[dict] = [{"type": "system", "subtype": "init"}]
    for i in range(n_errors + 1):
        target = "/w/inputs/wellbore.xml" if ignore else f"/w/inputs/deck{i}.xml"
        events.append(
            assistant(
                thinking("considering the deck"),
                tool_use("Edit", f"t{i}", file_path=target, new_string="<SinglePhaseFVM logLevl='1'/>"),
            )
        )
        if i < n_errors:
            events.append(user(tool_result(f"t{i}", UNKNOWN_ATTR, is_error=True)))
    events.append({"type": "result", "duration_ms": 630_000, "usage": {"output_tokens": 4321}})
    return write_stream(path, events)


# --------------------------------------------------------------------------
# structural diagnosis helpers (ported from repo3's extract.py)
# --------------------------------------------------------------------------

DETAIL = {
    "tag": "Problem",
    "score": 0.5,
    "n_gt_children": 3,
    "n_matched": 2,
    "n_extra": 2,
    "children": [
        {"tag": "Solvers", "score": 0.1, "n_gt_children": 4, "n_matched": 1, "n_extra": 2},
        {"tag": "Mesh", "score": 0.9, "n_gt_children": 2, "n_matched": 2, "n_extra": 0},
        {
            "tag": "Events",
            "score": 0.6,
            "n_gt_children": 1,
            "n_matched": 1,
            "n_extra": 0,
            "children": [{"tag": "PeriodicEvent", "name": "solve", "score": 0.0, "n_gt_children": 0}],
        },
    ],
}


def test_worst_subtrees_ranks_by_impact_not_score():
    rows = worst_subtrees(DETAIL, k=5)
    paths = [r["path"] for r in rows]
    # Solvers scores 0.1 over 4 GT children -> impact 4.5; Events scores 0.6
    # over 1 -> impact 0.8. A leaf at 0.0 must not appear at all.
    assert paths[0] == "/Problem/Solvers"
    assert "/Problem/Events/PeriodicEvent[solve]" not in paths
    assert rows[0]["impact"] > rows[-1]["impact"]
    assert rows[0]["missing_child_count"] == 3


def test_worst_subtrees_tolerates_missing_tags_and_empty_detail():
    assert worst_subtrees(None) == []
    assert worst_subtrees({}) == []
    assert worst_subtrees({"score": 0.0, "n_gt_children": 2}) == [
        {
            "path": "/?",
            "score": 0.0,
            "attr_score": 1.0,
            "n_gt_children": 2,
            "n_matched": 0,
            "n_extra": 0,
            "children_score": 1.0,
            "impact": 3.0,
            "missing_child_count": 2,
        }
    ]


def test_per_section_and_diagnosis_from_tree():
    sections = per_section(DETAIL)
    assert sections["Solvers"] == {"score": 0.1, "n_gt_children": 4, "n_matched": 1, "n_extra": 2}
    diagnosis = diagnosis_from_tree(
        DETAIL,
        gt_element_types=["Solvers", "Mesh", "Events", "Constitutive"],
        gen_element_types=["Solvers", "Mesh", "Events", "Hallucinated"],
        category="missing_block",
    )
    assert diagnosis.missing_elements == ["Constitutive"]
    assert diagnosis.extra_elements == ["Hallucinated"]
    assert diagnosis.weakest_sections(1) == [("Solvers", 0.1)]
    assert diagnosis.category == "missing_block"
    # Match counts have no home in Diagnosis.section_scores (float-valued), so
    # they are preserved as notes rather than dropped.
    assert any("1/4 children matched" in n for n in diagnosis.notes)


# --------------------------------------------------------------------------
# entity extraction — the informativeness proxy
# --------------------------------------------------------------------------


def test_extract_entities_separates_located_from_bare_feedback():
    assert extract_entities("Error: the run failed") == ()
    assert extract_entities("") == ()
    named = extract_entities(UNKNOWN_ATTR)
    assert "logLevl" in named
    assert "SinglePhaseFVM" in named
    assert "wellbore.xml" in named


def test_extract_entities_drops_generic_runtime_tokens_and_caps():
    assert extract_entities("StackTrace / RuntimeError raised") == ()
    long_text = " ".join(f"<Element{i}>" for i in range(40))
    assert len(extract_entities(long_text, limit=5)) == 5


# --------------------------------------------------------------------------
# trajectory mining, including graceful degradation
# --------------------------------------------------------------------------


def test_mine_trajectory_missing_file_returns_populated_no_data(tmp_path):
    features = mine_trajectory(tmp_path / "nope.jsonl")
    assert features.available is False
    assert features.n_tool_uses == 0
    assert features.tool_counts == {}
    assert features.calls == [] and features.feedback == []
    assert any("missing" in n for n in features.notes)
    assert "unavailable" in features.render()


def test_mine_trajectory_none_path_and_empty_file(tmp_path):
    assert mine_trajectory(None).available is False
    empty = tmp_path / "events.jsonl"
    empty.write_text("", encoding="utf-8")
    features = mine_trajectory(empty)
    assert features.available is False
    assert any("empty" in n for n in features.notes)


def test_mine_trajectory_skips_malformed_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(assistant(tool_use("Read", "a", file_path="/w/x.xml")))
        + "\n{not json\n\n"
        + json.dumps(assistant(tool_use("Read", "b", file_path="/w/x.xml")))
        + "\n{\"type\": \"assistant\", \"message\":",  # truncated final line
        encoding="utf-8",
    )
    features = mine_trajectory(path)
    assert features.available is True
    assert features.n_tool_uses == 2
    assert features.n_re_read_files == 1


def test_mine_trajectory_counts_actions_errors_and_hook_blocks(tmp_path):
    events = [
        assistant(thinking("plan"), tool_use("Read", "r1", file_path="/lib/docs/guide.rst")),
        user(tool_result("r1", "…contents…")),
        assistant(tool_use("Grep", "g1", pattern="SinglePhaseFVM")),
        user(tool_result("g1", "Error: bad regex", is_error=True)),
        assistant(tool_use("Write", "w1", file_path="/w/inputs/deck.xml", content="<Problem/>")),
        user(text("Stop blocked by verify_outputs hook: XML parse error in deck.xml.")),
        assistant(tool_use("Edit", "e1", file_path="/w/inputs/deck.xml", new_string="<Problem></Problem>")),
        {"type": "result", "duration_ms": 90_000},
    ]
    path = write_stream(tmp_path / "events.jsonl", events)
    hook_log = tmp_path / ".verify_hook_events.jsonl"
    write_stream(
        hook_log,
        [
            {"decision": "block", "reason_category": "parse_error", "retries_so_far": 1},
            {"decision": "allow", "reason_category": "xml_clean", "retries_so_far": 1},
        ],
    )

    features = mine_trajectory(
        path,
        hook_events_path=hook_log,
        config=MiningConfig(library_prefixes=("/lib",), validator_commands=("geosx",)),
    )
    assert features.available is True
    assert features.tool_counts == {"Read": 1, "Grep": 1, "Write": 1, "Edit": 1}
    assert features.tool_error_counts == {"Grep": 1}
    assert features.n_tool_errors == 1
    assert features.library_reads == 1 and features.doc_reads == 1
    assert features.n_artifact_writes == 1 and features.n_artifact_edits == 1
    assert features.top_grep_queries == ["SinglePhaseFVM"]
    assert features.wall_seconds == pytest.approx(90.0)
    # The hook log and the transcript are independent records of the same block.
    assert features.n_hook_blocks == 1
    assert features.hook_reason_categories == {"parse_error": 1, "xml_clean": 1}
    sources = [f.source for f in features.feedback]
    assert sources == ["tool_error", "hook"]
    assert "parse error" in features.feedback[1].text
    assert "Grep" in features.render()


def test_mine_trajectory_positions_feedback_between_actions(tmp_path):
    path = erroring_trajectory(tmp_path / "events.jsonl", n_errors=1)
    features = mine_trajectory(path)
    event = features.feedback[0]
    assert features.prev_call_before(event.index).target.endswith("deck0.xml")
    assert features.next_call_after(event.index).target.endswith("deck1.xml")
    assert len(features.calls_after(event.index, 4)) == 1


def test_trajectory_excerpt_keeps_the_environment_side(tmp_path):
    path = erroring_trajectory(tmp_path / "events.jsonl", n_errors=2)
    turns = trajectory_excerpt(path, n_tail_turns=3)
    assert len(turns) == 3
    assert any(t.role == "environment" for t in turns)
    rendered = "\n".join(t.render() for t in turns)
    assert "logLevl" in rendered
    assert "Edit" in rendered
    assert trajectory_excerpt(tmp_path / "missing.jsonl") == []
    assert trajectory_excerpt(None) == []


# --------------------------------------------------------------------------
# EFC — each component isolated
# --------------------------------------------------------------------------


def single_feedback_features(tmp_path, text_body: str, *, follow_up: dict | None = None):
    """One feedback event with one action either side of it."""
    events = [
        assistant(tool_use("Edit", "t0", file_path="/w/a.xml", new_string="<A/>")),
        user(tool_result("t0", text_body, is_error=True)),
        assistant(follow_up or tool_use("Edit", "t1", file_path="/w/b.xml", new_string="<B/>")),
    ]
    return mine_trajectory(write_stream(tmp_path / "events.jsonl", events))


def test_informativeness_rewards_naming_not_length(tmp_path):
    bare = efc_report(single_feedback_features(tmp_path / "a", "Error: the run failed"))
    padded = "Error: the run failed. " + ("blah " * 400)
    long_bare = efc_report(single_feedback_features(tmp_path / "b", padded))
    named = efc_report(single_feedback_features(tmp_path / "c", UNKNOWN_ATTR))

    assert bare.informative_mean == pytest.approx(EFCConfig().bare_informativeness)
    assert long_bare.informative_mean == pytest.approx(bare.informative_mean)
    assert named.informative_mean == pytest.approx(1.0)
    assert named.efc > bare.efc


def test_validity_tracks_whether_the_agent_engaged_the_named_entity(tmp_path):
    addressed = efc_report(
        single_feedback_features(
            tmp_path / "a",
            UNKNOWN_ATTR,
            follow_up=tool_use("Edit", "t1", file_path="/w/wellbore.xml", new_string="logLevel='1'"),
        )
    )
    unrelated = efc_report(
        single_feedback_features(
            tmp_path / "b",
            UNKNOWN_ATTR,
            follow_up=tool_use("Bash", "t1", command="ls /tmp"),
        )
    )
    cfg = EFCConfig()
    assert addressed.valid_mean == pytest.approx(cfg.validity_hit)
    assert unrelated.valid_mean == pytest.approx(cfg.validity_miss)
    assert addressed.efc > unrelated.efc


def test_validity_is_unknown_when_nothing_is_named(tmp_path):
    report = efc_report(single_feedback_features(tmp_path / "a", "Error: the run failed"))
    assert report.valid_mean == pytest.approx(EFCConfig().validity_unknown)


def test_retention_zero_when_the_agent_repeats_the_same_action(tmp_path):
    ignored = mine_trajectory(erroring_trajectory(tmp_path / "a" / "events.jsonl", 1, ignore=True))
    heeded = mine_trajectory(erroring_trajectory(tmp_path / "b" / "events.jsonl", 1))
    ignored_report = efc_report(ignored)
    heeded_report = efc_report(heeded)

    assert ignored_report.retention_mean == pytest.approx(0.0)
    assert ignored_report.efc == pytest.approx(0.0)
    assert heeded_report.retention_mean == pytest.approx(1.0)
    assert heeded_report.efc > 0.0
    assert "informative_but_ignored" in ignored_report.flags


def test_retention_partial_credit_for_adjusting_in_place(tmp_path):
    events = [
        assistant(tool_use("Edit", "t0", file_path="/w/a.xml", new_string="<A/>")),
        user(tool_result("t0", UNKNOWN_ATTR, is_error=True)),
        assistant(tool_use("Edit", "t1", file_path="/w/a.xml", new_string="<SinglePhaseFVM/>")),
    ]
    report = efc_report(mine_trajectory(write_stream(tmp_path / "events.jsonl", events)))
    assert report.retention_mean == pytest.approx(EFCConfig().retention_same_target)


def test_repeated_identical_feedback_does_not_scale_efc_linearly(tmp_path):
    one = efc_report(mine_trajectory(erroring_trajectory(tmp_path / "a" / "events.jsonl", 1)))
    three = efc_report(mine_trajectory(erroring_trajectory(tmp_path / "b" / "events.jsonl", 3)))

    assert three.n_events == 3
    assert [round(e.novel, 4) for e in three.events] == [1.0, 0.35, 0.1225]
    assert three.efc > one.efc  # more feedback is still worth something
    assert three.efc < 2 * one.efc  # but three copies are worth well under three
    assert "low_novelty" not in one.flags


def test_redundancy_signature_ignores_counters_and_line_numbers(tmp_path):
    events = [
        assistant(tool_use("Edit", "t0", file_path="/w/a.xml", new_string="x")),
        user(tool_result("t0", "Error in <Solvers> at line 12 (retry 1)", is_error=True)),
        assistant(tool_use("Edit", "t1", file_path="/w/b.xml", new_string="y")),
        user(tool_result("t1", "Error in <Solvers> at line 44 (retry 2)", is_error=True)),
        assistant(tool_use("Edit", "t2", file_path="/w/c.xml", new_string="z")),
    ]
    report = efc_report(mine_trajectory(write_stream(tmp_path / "events.jsonl", events)))
    assert report.events[1].n_prior_occurrences == 1
    assert report.events[1].novel < 1.0


def test_terminal_validator_events_earn_no_retention(tmp_path):
    features = mine_trajectory(erroring_trajectory(tmp_path / "events.jsonl", 1))
    report = efc_report(
        features,
        validator_events=[
            {"source": "geosx", "severity": "error", "message": UNKNOWN_ATTR, "location": "wellbore.xml:12"}
        ],
    )
    terminal = [e for e in report.events if e.source == "validator"]
    assert len(terminal) == 1
    assert terminal[0].retained == pytest.approx(0.0)
    assert terminal[0].contribution == pytest.approx(0.0)
    assert any("retention 0 by construction" in n for n in report.notes)


def test_validator_events_with_a_step_index_are_positioned_inline(tmp_path):
    features = mine_trajectory(erroring_trajectory(tmp_path / "events.jsonl", 1))
    report = efc_report(
        features,
        validator_events=[{"message": UNKNOWN_ATTR, "index": features.calls[0].index}],
    )
    inline = [e for e in report.events if e.source == "validator"][0]
    assert inline.retained > 0.0
    assert inline.contribution > 0.0


def test_harness_efficiency_is_efc_per_unit_raw_compute(tmp_path):
    features = mine_trajectory(erroring_trajectory(tmp_path / "events.jsonl", 1))
    report = efc_report(features, cost=Cost(tool_calls=10, wall_seconds=600, output_tokens=2000))
    assert report.raw_compute["tool_calls"] == 10
    assert report.harness_efficiency == pytest.approx(report.efc / 10)
    assert report.efficiency["wall_minutes"] == pytest.approx(report.efc / 10)
    assert report.efficiency["output_ktokens"] == pytest.approx(report.efc / 2)

    per_minute = efc_report(features, config=EFCConfig(efficiency_basis="wall_minutes"))
    assert per_minute.harness_efficiency == pytest.approx(per_minute.efc / (630_000 / 1000 / 60))


def test_efc_report_is_zeroed_and_explained_when_no_trajectory_exists(tmp_path):
    report = efc_report(mine_trajectory(tmp_path / "gone.jsonl"))
    assert report.efc == 0.0
    assert report.n_events == 0
    assert report.efc_density == 0.0
    assert any("unavailable" in n for n in report.notes)
    assert "EFC 0.00" in report.render()


def test_efc_scalar_matches_the_report(tmp_path):
    features = mine_trajectory(erroring_trajectory(tmp_path / "events.jsonl", 2))
    assert efc(features) == pytest.approx(efc_report(features).efc)


def test_no_feedback_at_all_is_flagged(tmp_path):
    events = [assistant(tool_use("Read", "r1", file_path="/w/a.xml")), user(tool_result("r1", "ok"))]
    report = efc_report(mine_trajectory(write_stream(tmp_path / "events.jsonl", events)))
    assert report.efc == 0.0
    assert "no_feedback" in report.flags


def test_unearned_retention_flag_catches_churn_inducing_feedback(tmp_path):
    """High retention with low validity is what a hook that just nags looks like."""
    events: list[dict] = []
    for i in range(4):
        events.append(assistant(tool_use("Bash", f"t{i}", command=f"echo step{i}")))
        events.append(user(text(f"Stop blocked by the review hook: revisit <Section{i}> now.")))
    events.append(assistant(tool_use("Bash", "tz", command="echo done")))
    report = efc_report(mine_trajectory(write_stream(tmp_path / "events.jsonl", events)))
    assert report.retention_mean >= 0.8
    assert report.valid_mean <= 0.35
    assert "unearned_retention" in report.flags


# --------------------------------------------------------------------------
# the corpus
# --------------------------------------------------------------------------


def make_round(tmp_path=None) -> RoundEvidence:
    rollouts = [
        rollout("Wellbore", 0.80, seed=1),
        rollout("Wellbore", 0.76, seed=2),
        rollout("Hydrofrac", 0.0, seed=1, status="parse_error"),
        rollout("Hydrofrac", 0.40, seed=2),
        rollout("ThermoPoro", 0.90, seed=1),
        rollout("ThermoPoro", 0.90, seed=2),
    ]
    diagnoses = {
        "Hydrofrac": diagnosis_from_tree(
            DETAIL,
            gt_element_types=["Solvers", "Mesh", "Events", "Constitutive"],
            gen_element_types=["Solvers", "Mesh", "Events", "Bogus"],
            category="missing_block",
        )
    }
    return build_evidence(
        rollouts,
        candidate_id="c_012",
        parent_scores={"Wellbore": 0.70, "Hydrofrac": 0.50, "ThermoPoro": 0.90},
        diagnoses=diagnoses,
    )


def test_zero_rate_is_the_headline_l0_quantity():
    evidence = make_round()
    assert evidence.n_rollouts == 6
    assert evidence.n_zero == 1
    assert evidence.zero_rate == pytest.approx(1 / 6)
    assert evidence.tasks["Hydrofrac"].zero_rate == pytest.approx(0.5)
    assert evidence.tasks["ThermoPoro"].zero_rate == 0.0

    l0 = evidence.render(level=0)
    assert "zero-rate" in l0
    assert "1/6 rollouts scored zero" in l0
    assert "headline" in l0


def test_l0_reports_mean_sigma_cost_and_parent_deltas():
    evidence = make_round()
    assert evidence.mean == pytest.approx((0.78 + 0.20 + 0.90) / 3)
    assert evidence.sigma > 0
    assert evidence.mean_task_sigma > 0
    assert evidence.total_cost.tool_calls == 120

    l0 = evidence.render(level=0)
    assert "mean score" in l0 and "parent 0.700" in l0
    assert "Wellbore +0.080" in l0
    assert "REGRESSIONS: Hydrofrac -0.300" in l0
    assert "tool_calls=120" in l0


def test_parent_delta_is_none_for_a_task_the_parent_never_ran():
    evidence = build_evidence(
        [rollout("NewTask", 0.5)], candidate_id="c1", parent_scores={"Old": 0.3}
    )
    assert evidence.tasks["NewTask"].delta is None
    assert "n/a" in evidence.render(level=1)
    assert any("parent scored tasks" in n for n in evidence.notes)


def test_parent_may_be_another_corpus():
    parent = build_evidence([rollout("A", 0.4, candidate_id="c0")], candidate_id="c0")
    child = build_evidence([rollout("A", 0.9, candidate_id="c1")], candidate_id="c1", parent=parent)
    assert child.parent_id == "c0"
    assert child.tasks["A"].delta == pytest.approx(0.5)


def test_l1_lists_every_task_worst_first_with_status_and_delta():
    l1 = make_round().render(level=1)
    body = l1.split("## L1")[1]
    order = [line.split()[0] for line in body.splitlines()[2:] if line.strip()]
    assert order == ["Hydrofrac", "Wellbore", "ThermoPoro"]
    assert "parse_error" in body
    assert "-0.300" in body


def test_l2_explains_only_the_tasks_that_are_losing_score():
    l2 = make_round().render(level=2)
    assert "## L2" in l2
    assert "### Hydrofrac" in l2
    assert "### ThermoPoro" not in l2  # clean and unchanged: nothing to say
    assert "category=missing_block" in l2
    assert "weakest sections: Solvers 0.10" in l2
    assert "worst subtree: /Problem/Solvers" in l2
    assert "missing element types (1): Constitutive" in l2
    assert "extra element types (1, n_extra=2): Bogus" in l2


def test_l2_says_so_when_nothing_is_wrong():
    evidence = build_evidence([rollout("A", 1.0), rollout("B", 0.95)], candidate_id="c1")
    assert "no task is failing" in evidence.render(level=2)


def test_l2_degrades_when_the_simulator_returned_no_diagnosis():
    evidence = build_evidence(
        [rollout("A", 0.0, status="timeout", error="container exited 137")], candidate_id="c1"
    )
    l2 = evidence.render(level=2)
    assert "no diagnosis" in l2
    assert "container exited 137" in l2


def test_l3_is_a_menu_until_a_task_is_named():
    evidence = make_round()
    menu = evidence.render(level=3)
    assert "on demand" in menu
    assert 'render(level=3, task="<task>")' in menu
    # The costly part is absent until asked for.
    assert "tail trajectory excerpt" not in menu


def test_render_levels_are_cumulative():
    evidence = make_round()
    assert "## L1" not in evidence.render(level=0)
    assert "## L1" in evidence.render(level=1) and "## L2" not in evidence.render(level=1)
    assert "## L2" in evidence.render(level=2)


def test_l3_drill_down_is_on_demand_and_verbatim(tmp_path):
    events_path = erroring_trajectory(tmp_path / "events.jsonl", 2)
    long_validator = UNKNOWN_ATTR + "\n" + "\n".join(f"  attribute_{i}: real64" for i in range(300))
    rollouts = [
        rollout("Hydrofrac", 0.6, seed=1, events_path=str(events_path)),
        rollout(
            "Hydrofrac",
            0.1,
            seed=2,
            events_path=str(events_path),
            validator_events=[
                {"source": "geosx", "severity": "error", "location": "deck.xml:12", "message": long_validator}
            ],
        ),
    ]
    evidence = build_evidence(rollouts, candidate_id="c1", parent_scores={"Hydrofrac": 0.5})

    drill = evidence.drill_down("Hydrofrac")
    # Worst seed by default: seed 2 is where the information is.
    assert "seed 2" in drill
    assert "### validator output (verbatim)" in drill
    assert "attribute_299: real64" in drill  # no global character cap
    assert long_validator in drill
    assert "### mined trajectory features" in drill
    assert "### effective feedback compute" in drill
    assert "### tail trajectory excerpt" in drill
    assert "logLevl" in drill

    # And it composes with the cumulative levels.
    full = evidence.render(level=3, task="Hydrofrac")
    assert "## L0" in full and "## L2" in full and "drill-down: Hydrofrac" in full


def test_drill_down_can_target_a_named_seed(tmp_path):
    events_path = erroring_trajectory(tmp_path / "events.jsonl", 1)
    evidence = build_evidence(
        [
            rollout("A", 0.6, seed=1, events_path=str(events_path)),
            rollout("A", 0.1, seed=2, events_path=str(events_path)),
        ],
        candidate_id="c1",
    )
    assert "seed 1" in evidence.drill_down("A", seed=1)
    assert "no rollout for seed 9" in evidence.drill_down("A", seed=9)


def test_drill_down_on_an_unknown_task_names_what_is_available():
    out = make_round().drill_down("NotATask")
    assert "no rollouts for this task" in out
    assert "Hydrofrac" in out


def test_drill_down_degrades_when_the_trajectory_is_missing(tmp_path):
    evidence = build_evidence(
        [rollout("A", 0.0, events_path=str(tmp_path / "absent.jsonl"))], candidate_id="c1"
    )
    drill = evidence.drill_down("A")
    assert "trajectory: unavailable" in drill
    assert "(none recorded)" in drill  # no validator events either
    assert "(no trajectory excerpt available)" in drill
    assert "EFC 0.00" in drill


def test_compute_efc_populates_l0_and_l1(tmp_path):
    events_path = erroring_trajectory(tmp_path / "events.jsonl", 2)
    evidence = build_evidence(
        [
            rollout("A", 0.5, seed=1, events_path=str(events_path)),
            rollout("B", 0.5, seed=1, events_path=str(tmp_path / "missing.jsonl")),
        ],
        candidate_id="c1",
        with_efc=True,
    )
    assert evidence.tasks["A"].mean_efc > 0
    assert evidence.tasks["B"].mean_efc == 0.0  # missing logs score 0, not absent
    assert "EFC (mean/task)" in evidence.render(level=0)
    l1_header = evidence.render(level=1).split("## L1")[1].splitlines()[1]
    assert "EFC" in l1_header
    assert " 0.00" in evidence.render(level=1).split("## L1")[1]  # B's zero, shown not hidden


def test_compute_efc_reads_the_hook_log_next_to_the_workspace(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    events_path = erroring_trajectory(workspace / "events.jsonl", 1)
    write_stream(
        workspace / CorpusConfig().hook_events_filename,
        [{"decision": "block", "reason_category": "schema_error", "retries_so_far": 2}],
    )
    evidence = build_evidence(
        [rollout("A", 0.3, events_path=str(events_path), artifacts_dir=str(workspace))],
        candidate_id="c1",
    )
    assert "schema_error" in evidence.drill_down("A")
    assert "max_retries=2" in evidence.drill_down("A")


def test_corpus_serialises_without_touching_the_filesystem():
    payload = make_round().to_dict()
    assert payload["zero_rate"] == pytest.approx(1 / 6)
    assert payload["tasks"]["Hydrofrac"]["category"] == "missing_block"
    assert json.loads(json.dumps(payload))["n_rollouts"] == 6


def test_empty_round_renders_rather_than_dividing_by_zero():
    evidence = build_evidence([], candidate_id="c1")
    assert evidence.mean == 0.0
    assert evidence.zero_rate == 0.0
    assert "## L0" in evidence.render(level=2)
