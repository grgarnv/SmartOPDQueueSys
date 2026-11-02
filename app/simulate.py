"""Discrete-event simulation harness (SRS 3.8, Appendix A).

Generates synthetic OPD days from a scenario and a seed, runs them through the
same engine.py queue and ETA logic as the server, and compares the Smart OPD
policy with a fixed-token FIFO baseline on identical random draws.

It never opens the application database and never contacts a real notification
provider: alerts go to notify.MockProvider (SIM-004, NFR-005).

Usage:  python3 app/simulate.py --scenario all --seeds 100
"""
import argparse
import hashlib
import heapq
import json
import math
import random
import statistics
import subprocess
import time as wallclock
from datetime import datetime, timedelta
from pathlib import Path

import engine
import notify

OUT_DIR = Path(__file__).parent / "sim_results"
BASE = datetime(2026, 1, 5, 9, 0)  # simulated OPD opens at minute 0
BUFFER = 10        # patients aim to arrive this many minutes before their expected time
GRACE = 10         # no-show grace period, SRS default
ALERT_MIN = 30     # arrival alert threshold, SRS default
CHANGE_MIN = 15    # ETA shift that triggers a change alert
DAY_START = -60.0  # simulation starts one hour before OPD opens
HARD_STOP = 720.0  # safety stop, 12 hours after opening

# Distributions are documented assumptions, not measured hospital facts (SRS 6.3).
SCENARIOS = {
    "normal": dict(
        description="Expected arrival and consultation patterns.",
        doctors=3, patients=24, planned_avg=10, mean_consult=10, cv=0.4, no_show=0.08,
        late_sd=6, late_start=(0, 0), breaks=0, emergencies=0, notify_fail=0.02),
    "disruption": dict(
        description="Longer consultations, late doctor starts, a break and more no-shows.",
        doctors=3, patients=24, planned_avg=10, mean_consult=12, cv=0.7, no_show=0.15,
        late_sd=8, late_start=(10, 30), breaks=1, emergencies=0, notify_fail=0.02),
    "emergency": dict(
        description="Normal day plus two staff-entered emergency insertions per doctor.",
        doctors=3, patients=24, planned_avg=10, mean_consult=10, cv=0.4, no_show=0.08,
        late_sd=6, late_start=(0, 0), breaks=0, emergencies=2, notify_fail=0.02),
    "notification_degradation": dict(
        description="Normal day with half of all alerts failing.",
        doctors=3, patients=24, planned_avg=10, mean_consult=10, cv=0.4, no_show=0.08,
        late_sd=6, late_start=(0, 0), breaks=0, emergencies=0, notify_fail=0.5),
    "stress": dict(
        description="Higher volume with all disruptions combined.",
        doctors=3, patients=36, planned_avg=10, mean_consult=11, cv=0.7, no_show=0.15,
        late_sd=10, late_start=(5, 25), breaks=1, emergencies=2, notify_fail=0.2),
}

POLICIES = ("baseline", "smart")

METRICS = {  # name: definition, reported with every result (NFR-018)
    "eta_mae": "Mean absolute error in minutes between the ETA shown at check-in and the simulated actual consultation start.",
    "eta_median_ae": "Median absolute error, same pairing as eta_mae.",
    "eta_within_15": "Share of patients whose ETA at check-in was within 15 minutes of the actual start.",
    "wait_after_checkin": "Mean minutes between check-in and consultation start (physical waiting).",
    "eta_revisions": "Mean number of times a patient's ETA changed by at least 1 minute while waiting.",
    "eta_revision_size": "Mean absolute size in minutes of those ETA changes.",
    "throughput_per_hour": "Consultations completed per hour from OPD opening to the last completion.",
    "no_shows": "Mean patients per day who never arrived.",
    "skips": "Mean skip actions per day (grace period ran out).",
    "reinsertions": "Mean late arrivals reinserted after being skipped.",
    "notifications_sent": "Mean alert attempts per day.",
    "notification_failures": "Mean failed alert attempts per day.",
    "queue_order_violations": "Times a patient was started while an earlier eligible patient waited. Should be 0.",
}


def at(minute):
    return BASE + timedelta(minutes=minute)


def mins(dt):
    return (dt - BASE).total_seconds() / 60


class SimQueue:
    """Test adapter for one doctor's synthetic day. All state lives in this object."""

    def __init__(self, cfg, scenario, seed, doctor, policy):
        self.cfg, self.policy = cfg, policy
        self.key = f"{scenario}:{seed}:{doctor}"
        rng = random.Random(self.key)
        # Common random numbers: every draw happens here, identically for both policies (Appendix A3).
        k = 1 / cfg["cv"] ** 2
        self.entries = []
        for i in range(cfg["patients"]):
            self.entries.append({
                "id": i + 1, "status": "booked", "priority": 0, "position": i + 1,
                "started_at": None, "due_at": None, "emergency": False,
                "slot": i * cfg["planned_avg"], "promised": at(i * cfg["planned_avg"]),
                "duration": max(1.0, rng.gammavariate(k, cfg["mean_consult"] / k)),
                "no_show": rng.random() < cfg["no_show"],
                "lateness": rng.gauss(0, cfg["late_sd"]),
                "plan": 0, "eta": None, "told_eta": None, "arrival_sent": False, "check_at": None,
                "checkin_t": None, "eta_at_checkin": None, "start_t": None, "end_t": None,
                "revisions": 0, "revision_total": 0.0, "reinserted": False,
            })
        self.emergencies = []
        for j in range(cfg["emergencies"]):
            self.emergencies.append((rng.uniform(30, 180), max(1.0, rng.gammavariate(k, cfg["mean_consult"] / k)), j))
        self.late_start = rng.uniform(*cfg["late_start"])
        self.break_at = rng.uniform(90, 150) if cfg["breaks"] else None
        self.break_len = rng.uniform(15, 25)

        self.t = DAY_START
        self.heap, self.seq = [], 0
        self.present, self.busy = False, None
        self.blocked_until = None  # break or announced late start, known to the system
        self.break_pending = False
        self.durations = []
        self.trace = hashlib.sha256()
        self.n = dict(skips=0, reinsertions=0, sent=0, failed=0, violations=0)

    # ----- event plumbing -----
    def push(self, t, kind, data=None):
        self.seq += 1
        heapq.heappush(self.heap, (t, self.seq, kind, data))

    def by_id(self, i):
        return self.entries[i - 1]

    def plan_arrival(self, e, minute):
        e["plan"] += 1
        self.push(max(minute, self.t), "arrive", (e["id"], e["plan"]))

    # ----- run -----
    def run(self):
        self.push(self.late_start, "doctor_in")
        if self.late_start > 0:
            self.push(0.0, "late_announced")
        if self.break_at is not None:
            self.push(self.break_at, "break_due")
        for minute, duration, j in self.emergencies:
            self.push(minute, "emergency", (duration, j))
        for e in self.entries:
            if not e["no_show"]:  # everyone starts with the time they were given at booking
                self.plan_arrival(e, e["slot"] - BUFFER + e["lateness"])
        self.refresh()
        while self.heap:
            t, _, kind, data = heapq.heappop(self.heap)
            if t > HARD_STOP:
                break
            self.t = t
            if self.handle(kind, data):
                self.trace.update(f"{t:.4f}|{kind}|{data}\n".encode())
                self.try_call()
                self.refresh()
        return self.metrics()

    def handle(self, kind, data):
        """Apply one event. Returns False for stale events, which change nothing."""
        if kind == "doctor_in":
            self.present, self.blocked_until = True, None
        elif kind == "late_announced":
            self.blocked_until = self.late_start  # staff records the delay (doctor availability event)
        elif kind == "break_due":
            self.break_pending = True
        elif kind == "break_end":
            self.blocked_until = None
        elif kind == "end":
            e = self.by_id(data)
            e["status"], e["end_t"] = "completed", self.t
            self.durations.append(e["end_t"] - e["start_t"])
            self.busy = None
        elif kind == "emergency":
            duration, j = data
            e = {"id": len(self.entries) + 1, "status": "checked_in", "priority": 1,
                 "position": engine.end_position(self.entries), "started_at": None, "due_at": None,
                 "emergency": True, "duration": duration, "no_show": False, "plan": 0, "eta": None,
                 "checkin_t": self.t, "eta_at_checkin": None, "start_t": None, "end_t": None,
                 "revisions": 0, "revision_total": 0.0, "reinserted": False, "check_at": None}
            self.entries.append(e)
        elif kind == "arrive":
            e = self.by_id(data[0])
            if data[1] != e["plan"]:
                return False
            if e["status"] == "booked":
                e["status"] = "checked_in"
            elif e["status"] == "skipped":  # late arrival goes to the end of the queue (FR-026)
                e.update(status="checked_in", due_at=None, position=engine.end_position(self.entries), reinserted=True)
                self.n["reinsertions"] += 1
            else:
                return False
            e["checkin_t"] = self.t
            self.refresh()
            e["eta_at_checkin"] = e["eta"] if self.policy == "smart" else e["slot"]
        elif kind == "alert_check":
            e = self.by_id(data[0])
            if e["check_at"] != data[1]:
                return False
        # "grace" needs no state change: try_call skips patients whose grace has run out
        return True

    def try_call(self):
        """The doctor's side of the queue, using the same engine calls as the server."""
        if not self.present or self.busy or self.blocked_until is not None:
            return
        if self.break_pending:
            self.break_pending = False
            self.blocked_until = self.t + self.break_len
            self.push(self.blocked_until, "break_end")
            return
        now = at(self.t)
        for e in self.entries:
            if engine.can_skip(e, now, GRACE):
                e["status"] = "skipped"
                self.n["skips"] += 1
        chosen, missed = engine.next_to_call(self.entries)
        for e in missed:
            if e["due_at"] is None:
                e["due_at"] = engine.turn_cutoff(e, now)
                self.push(mins(e["due_at"]) + GRACE, "grace", e["id"])
        if not chosen:
            return
        for other in self.entries:  # independent check of the engine's ordering
            if (other is not chosen and other["status"] == "checked_in"
                    and (other["priority"], -other["position"]) > (chosen["priority"], -chosen["position"])):
                self.n["violations"] += 1
        chosen.update(status="in_consultation", started_at=now, start_t=self.t)
        self.busy = chosen
        self.push(self.t + chosen["duration"], "end", chosen["id"])

    def refresh(self):
        """Event-driven ETA refresh and alerts. The baseline keeps its fixed token times."""
        if self.policy == "baseline":
            for e in self.entries:
                if e["eta"] is None:
                    e["eta"] = e["slot"] if not e["emergency"] else None
            return
        avg = engine.expected_minutes(self.durations, self.cfg["planned_avg"])
        etas = engine.compute_etas(self.entries, at(self.t), avg, opd_start=at(0),
                                   break_until=at(self.blocked_until) if self.blocked_until is not None else None)
        for e in self.entries:
            if e["status"] not in engine.WAITING or e["emergency"]:
                continue
            new = mins(etas[e["id"]])
            if e["eta"] is not None and abs(new - e["eta"]) >= 1:
                e["revisions"] += 1
                e["revision_total"] += abs(new - e["eta"])
            if e["eta"] is None or abs(new - e["eta"]) >= 1:
                e["eta"] = new
            if e["told_eta"] is None:
                e["told_eta"] = e["slot"]  # the time given at booking
            if e["status"] != "booked":
                continue
            to_eta = e["eta"] - self.t
            for purpose in notify.alert_purposes(to_eta, abs(e["eta"] - e["told_eta"]), e["arrival_sent"], ALERT_MIN, CHANGE_MIN):
                self.alert(e, purpose)
            if not e["arrival_sent"]:
                check = max(self.t + 0.01, e["eta"] - ALERT_MIN)
                if e["check_at"] != check:
                    e["check_at"] = check
                    self.push(check, "alert_check", (e["id"], check))

    def alert(self, e, purpose):
        """Send through the mock provider. A delivered alert makes the patient re-plan their arrival."""
        self.n["sent"] += 1
        attempt = self.n["sent"]
        fail = random.Random(f"{self.key}:{e['id']}:{purpose}:{attempt}").random() < self.cfg["notify_fail"]
        e["told_eta"], e["promised"] = e["eta"], at(e["eta"])
        if purpose == "arrival":
            e["arrival_sent"] = True
        try:
            notify.MockProvider().send(f"synthetic-{e['id']}", purpose, f"ETA {e['eta']:.0f}", fail=fail)
        except ConnectionError:
            self.n["failed"] += 1
            return
        if not e["no_show"]:
            self.plan_arrival(e, max(self.t, e["eta"] - BUFFER + e["lateness"]))

    def metrics(self):
        served = [e for e in self.entries if e["start_t"] is not None and not e["emergency"]]
        errors = [abs(e["start_t"] - e["eta_at_checkin"]) for e in served if e["eta_at_checkin"] is not None]
        waits = [e["start_t"] - e["checkin_t"] for e in served]
        revised = [e for e in self.entries if not e["emergency"]]
        ends = [e["end_t"] for e in self.entries if e["end_t"] is not None]
        total_revs = sum(e["revisions"] for e in revised)
        return {
            "errors": errors, "waits": waits,
            "revisions": total_revs, "revision_total": sum(e["revision_total"] for e in revised), "patients": len(revised),
            "completed": len(ends), "last_end": max(ends, default=0.0),
            "no_shows": sum(e["no_show"] for e in self.entries),
            **self.n, "trace": self.trace.hexdigest(),
        }


def run_day(scenario, seed, policy):
    """One synthetic OPD day for every doctor in the scenario, pooled into day-level metrics."""
    cfg = SCENARIOS[scenario]
    started = wallclock.perf_counter()
    parts = [SimQueue(cfg, scenario, seed, d, policy).run() for d in range(cfg["doctors"])]
    errors = [x for p in parts for x in p["errors"]]
    waits = [x for p in parts for x in p["waits"]]
    revisions = sum(p["revisions"] for p in parts)
    hours = max(p["last_end"] for p in parts) / 60
    trace = hashlib.sha256("".join(p["trace"] for p in parts).encode()).hexdigest()
    return {
        "eta_mae": statistics.fmean(errors) if errors else None,
        "eta_median_ae": statistics.median(errors) if errors else None,
        "eta_within_15": sum(x <= 15 for x in errors) / len(errors) if errors else None,
        "wait_after_checkin": statistics.fmean(waits) if waits else None,
        "eta_revisions": revisions / sum(p["patients"] for p in parts),
        "eta_revision_size": sum(p["revision_total"] for p in parts) / revisions if revisions else 0.0,
        "throughput_per_hour": sum(p["completed"] for p in parts) / hours if hours > 0 else None,
        "no_shows": sum(p["no_shows"] for p in parts),
        "skips": sum(p["skips"] for p in parts),
        "reinsertions": sum(p["reinsertions"] for p in parts),
        "notifications_sent": sum(p["sent"] for p in parts),
        "notification_failures": sum(p["failed"] for p in parts),
        "queue_order_violations": sum(p["violations"] for p in parts),
        "runtime_ms": round((wallclock.perf_counter() - started) * 1000, 2),
        "trace_sha256": trace,
    }


def summarise(values):
    """Mean with a normal-approximation 95% confidence interval across seeds."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    mean = statistics.fmean(vals)
    half = 1.96 * statistics.stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else 0.0
    return {"mean": mean, "ci_low": mean - half, "ci_high": mean + half, "n": len(vals)}


def software_version():
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=Path(__file__).parent, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    return f"{engine.VERSION}+{commit}" if commit else engine.VERSION


def run_experiment(scenarios, seeds, seed_start=1, out_dir=OUT_DIR, progress=None):
    """Run every scenario for every seed under both policies, then write JSON and Markdown reports."""
    started = wallclock.perf_counter()
    seed_list = list(range(seed_start, seed_start + seeds))
    results = {}
    for name in scenarios:
        runs = []
        for seed in seed_list:
            runs.append({"seed": seed, **{p: run_day(name, seed, p) for p in POLICIES}})
            if progress:
                progress(name, seed)
        summary = {}
        for metric in METRICS:
            summary[metric] = {p: summarise([r[p][metric] for r in runs]) for p in POLICIES}
            summary[metric]["difference"] = summarise(
                [r["smart"][metric] - r["baseline"][metric] for r in runs
                 if r["smart"][metric] is not None and r["baseline"][metric] is not None])
        results[name] = {"config": SCENARIOS[name], "runs": runs, "summary": summary}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}-{'-'.join(scenarios) if len(scenarios) < 3 else 'multi'}-{seeds}seeds"
    report = {
        "run_id": run_id, "label": "SIMULATED RESULTS", "created_at": datetime.now().isoformat(timespec="seconds"),
        "software_version": software_version(), "scenarios": scenarios, "seeds": seed_list,
        "runs_per_scenario": len(seed_list), "target_runs_per_scenario": 100,
        "assumptions": {"buffer_minutes": BUFFER, "grace_minutes": GRACE, "alert_minutes": ALERT_MIN,
                        "change_alert_minutes": CHANGE_MIN},
        "metric_definitions": METRICS, "results": results,
        "runtime_seconds": round(wallclock.perf_counter() - started, 2),
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{run_id}.json").write_text(json.dumps(report, indent=1))
    (out_dir / f"{run_id}.md").write_text(markdown_report(report))
    return report


def fmt(s, pct=False):
    if s is None:
        return "n/a"
    f = (lambda v: f"{v * 100:.1f}%") if pct else (lambda v: f"{v:.2f}")
    return f"{f(s['mean'])} [{f(s['ci_low'])}, {f(s['ci_high'])}]"


def markdown_report(r):
    out = [f"# Smart OPD simulation report: {r['run_id']}", "",
           "**SIMULATED RESULTS.** These come from synthetic data and model assumptions. They do not show real-world "
           "effectiveness, clinical safety or actual reductions in hospital waiting time (SIM-010).", "",
           f"- Software version: {r['software_version']}",
           f"- Created: {r['created_at']}",
           f"- Seeds per scenario: {r['runs_per_scenario']} (target 100){' - below target' if r['runs_per_scenario'] < 100 else ''}",
           f"- Seeds: {r['seeds'][0]} to {r['seeds'][-1]}",
           f"- Runtime: {r['runtime_seconds']} s",
           f"- Patient assumptions: aim to arrive {BUFFER} min early; grace period {GRACE} min; arrival alert {ALERT_MIN} min before ETA; change alert at {CHANGE_MIN} min shift.",
           "- Baseline: fixed token times (token order x planned consultation length), no event-driven ETA refresh, no alerts. "
           "Smart OPD: event-driven ETA from engine.py with arrival and change alerts. Both run on identical random draws.",
           "", "Values are means across seeds with 95% confidence intervals in brackets.", ""]
    for name, res in r["results"].items():
        cfg = res["config"]
        out += [f"## Scenario: {name}", "", cfg["description"], "",
                "Configuration: " + ", ".join(f"{k}={v}" for k, v in cfg.items() if k != "description"), "",
                "| Metric | Baseline | Smart OPD | Difference (Smart - Baseline) |", "|---|---|---|---|"]
        for metric in METRICS:
            s = res["summary"][metric]
            pct = metric == "eta_within_15"
            out.append(f"| {metric} | {fmt(s['baseline'], pct)} | {fmt(s['smart'], pct)} | {fmt(s['difference'], pct)} |")
        within = res["summary"]["eta_within_15"]["smart"]
        if name == "normal" and within:
            met = "met" if within["mean"] >= 0.8 else "not met"
            out += ["", f"Engineering target for normal days (at least 80% of ETAs within 15 minutes): **{met}** "
                        f"({within['mean'] * 100:.1f}% simulated)."]
        out.append("")
    out += ["## Metric definitions", ""] + [f"- **{k}**: {v}" for k, v in METRICS.items()]
    out += ["", "## Limitations", "",
            "Synthetic data is only as realistic as these assumptions. The model does not capture real human behaviour, "
            "clinical judgement, hospital-specific exceptions, connectivity or organisational constraints. Each doctor's "
            "queue is simulated independently, and patients always follow alerts that reach them. Results must be "
            "described as simulated outcomes (Appendix A6).", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Run Smart OPD simulations (synthetic data only).")
    ap.add_argument("--scenario", default="all", help=f"one of {', '.join(SCENARIOS)} or 'all'")
    ap.add_argument("--seeds", type=int, default=100)
    ap.add_argument("--seed-start", type=int, default=1)
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()
    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    for s in scenarios:
        if s not in SCENARIOS:
            ap.error(f"unknown scenario {s}")
    report = run_experiment(scenarios, args.seeds, args.seed_start, args.out)
    print(f"Wrote {args.out}/{report['run_id']}.md and .json in {report['runtime_seconds']} s")
    for name, res in report["results"].items():
        s = res["summary"]
        print(f"  {name:26} ETA within 15 min: baseline {fmt(s['eta_within_15']['baseline'], True)}, "
              f"smart {fmt(s['eta_within_15']['smart'], True)}; MAE baseline {fmt(s['eta_mae']['baseline'])}, smart {fmt(s['eta_mae']['smart'])}")


if __name__ == "__main__":
    main()
