"""Checks for the simulation harness. Run: python3 app/test_sim.py"""
import json
import sys
import tempfile
from pathlib import Path

import simulate


def test_same_seed_reproduces_the_same_day():  # SIM-003, NFR-017, AC-009
    for scenario in simulate.SCENARIOS:
        a, b = simulate.run_day(scenario, 42, "smart"), simulate.run_day(scenario, 42, "smart")
        a.pop("runtime_ms"), b.pop("runtime_ms")
        assert a == b, scenario


def test_different_seeds_differ():
    assert simulate.run_day("normal", 1, "smart")["trace_sha256"] != simulate.run_day("normal", 2, "smart")["trace_sha256"]


def test_policies_share_random_draws():  # Appendix A3: same patients, same durations, same no-shows
    for scenario in simulate.SCENARIOS:
        assert simulate.run_day(scenario, 3, "baseline")["no_shows"] == simulate.run_day(scenario, 3, "smart")["no_shows"]


def test_engine_never_breaks_queue_order():
    for scenario in simulate.SCENARIOS:
        for seed in range(1, 11):
            for policy in simulate.POLICIES:
                assert simulate.run_day(scenario, seed, policy)["queue_order_violations"] == 0, (scenario, seed, policy)


def test_baseline_sends_no_alerts_and_never_revises():  # SIM-005
    r = simulate.run_day("stress", 5, "baseline")
    assert r["notifications_sent"] == 0 and r["eta_revisions"] == 0


def test_every_no_show_is_skipped_not_deleted():  # FR-025 in simulation
    r = simulate.run_day("normal", 9, "smart")
    assert r["skips"] >= r["no_shows"]


def test_harness_is_isolated_from_the_app():  # SIM-004, SIM-011, NFR-005
    simulate.run_day("normal", 1, "smart")
    assert "server" not in sys.modules and "sqlite3" not in sys.modules


def test_report_is_labelled_and_complete():  # SIM-009, SIM-010, NFR-016, NFR-018
    with tempfile.TemporaryDirectory() as d:
        r = simulate.run_experiment(["normal", "stress"], 3, out_dir=d)
        files = sorted(p.suffix for p in Path(d).iterdir())
        assert files == [".json", ".md"]
        saved = json.loads((Path(d) / f"{r['run_id']}.json").read_text())
        md = (Path(d) / f"{r['run_id']}.md").read_text()
    assert saved["label"] == "SIMULATED RESULTS" and "SIMULATED RESULTS" in md
    assert saved["seeds"] == [1, 2, 3] and saved["software_version"].startswith(simulate.engine.VERSION)
    assert "below target" in md, "fewer than 100 seeds must be disclosed (AC-011)"
    for name in ("normal", "stress"):
        summary = saved["results"][name]["summary"]
        assert set(summary) == set(simulate.METRICS)
        assert summary["eta_mae"]["smart"]["n"] == 3 and "difference" in summary["eta_mae"]
    assert "Limitations" in md and "do not show real-world" in md


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("simulator: all checks passed")
