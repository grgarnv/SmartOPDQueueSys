# Smart OPD simulation report: 20261102-223106-multi-100seeds

**SIMULATED RESULTS.** These come from synthetic data and model assumptions. They do not show real-world effectiveness, clinical safety or actual reductions in hospital waiting time (SIM-010).

- Software version: 1.0.0+ddbd703
- Created: 2026-11-02T22:31:06
- Seeds per scenario: 100 (target 100)
- Seeds: 1 to 100
- Runtime: 4.25 s
- Patient assumptions: aim to arrive 10 min early; grace period 10 min; arrival alert 30 min before ETA; change alert at 15 min shift.
- Baseline: fixed token times (token order x planned consultation length), no event-driven ETA refresh, no alerts. Smart OPD: event-driven ETA from engine.py with arrival and change alerts. Both run on identical random draws.

Values are means across seeds with 95% confidence intervals in brackets.

## Scenario: normal

Expected arrival and consultation patterns.

Configuration: doctors=3, patients=24, planned_avg=10, mean_consult=10, cv=0.4, no_show=0.08, late_sd=6, late_start=(0, 0), breaks=0, emergencies=0, notify_fail=0.02

| Metric | Baseline | Smart OPD | Difference (Smart - Baseline) |
|---|---|---|---|
| eta_mae | 7.42 [6.90, 7.95] | 5.24 [5.07, 5.40] | -2.19 [-2.75, -1.63] |
| eta_median_ae | 5.94 [5.54, 6.34] | 3.74 [3.57, 3.91] | -2.20 [-2.61, -1.78] |
| eta_within_15 | 88.4% [86.3%, 90.5%] | 95.1% [94.6%, 95.7%] | 6.7% [4.7%, 8.8%] |
| wait_after_checkin | 10.99 [10.18, 11.80] | 10.18 [9.92, 10.43] | -0.81 [-1.53, -0.10] |
| eta_revisions | 0.00 [0.00, 0.00] | 13.93 [13.56, 14.31] | 13.93 [13.56, 14.31] |
| eta_revision_size | 0.00 [0.00, 0.00] | 5.14 [5.03, 5.24] | 5.14 [5.03, 5.24] |
| throughput_per_hour | 15.65 [15.48, 15.81] | 15.62 [15.38, 15.86] | -0.02 [-0.17, 0.12] |
| no_shows | 5.98 [5.51, 6.45] | 5.98 [5.51, 6.45] | 0.00 [0.00, 0.00] |
| skips | 5.99 [5.53, 6.45] | 6.25 [5.75, 6.75] | 0.26 [0.14, 0.38] |
| reinsertions | 0.01 [-0.01, 0.03] | 0.27 [0.16, 0.38] | 0.26 [0.14, 0.38] |
| notifications_sent | 0.00 [0.00, 0.00] | 166.70 [161.57, 171.83] | 166.70 [161.57, 171.83] |
| notification_failures | 0.00 [0.00, 0.00] | 3.60 [3.15, 4.05] | 3.60 [3.15, 4.05] |
| queue_order_violations | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |

Engineering target for normal days (at least 80% of ETAs within 15 minutes): **met** (95.1% simulated).

## Scenario: disruption

Longer consultations, late doctor starts, a break and more no-shows.

Configuration: doctors=3, patients=24, planned_avg=10, mean_consult=12, cv=0.7, no_show=0.15, late_sd=8, late_start=(10, 30), breaks=1, emergencies=0, notify_fail=0.02

| Metric | Baseline | Smart OPD | Difference (Smart - Baseline) |
|---|---|---|---|
| eta_mae | 37.23 [34.84, 39.62] | 12.17 [11.65, 12.70] | -25.06 [-27.45, -22.67] |
| eta_median_ae | 32.15 [29.54, 34.76] | 8.90 [8.58, 9.21] | -23.25 [-25.85, -20.66] |
| eta_within_15 | 27.2% [24.3%, 30.0%] | 72.5% [71.2%, 73.7%] | 45.3% [42.4%, 48.3%] |
| wait_after_checkin | 45.91 [43.38, 48.44] | 15.92 [15.45, 16.40] | -29.98 [-32.33, -27.63] |
| eta_revisions | 0.00 [0.00, 0.00] | 21.01 [20.49, 21.52] | 21.01 [20.49, 21.52] |
| eta_revision_size | 0.00 [0.00, 0.00] | 7.88 [7.68, 8.08] | 7.88 [7.68, 8.08] |
| throughput_per_hour | 11.48 [11.25, 11.70] | 10.66 [10.44, 10.88] | -0.81 [-0.92, -0.71] |
| no_shows | 10.83 [10.31, 11.35] | 10.83 [10.31, 11.35] | 0.00 [0.00, 0.00] |
| skips | 10.84 [10.32, 11.36] | 11.98 [11.37, 12.59] | 1.14 [0.83, 1.45] |
| reinsertions | 0.01 [-0.01, 0.03] | 1.15 [0.84, 1.46] | 1.14 [0.83, 1.45] |
| notifications_sent | 0.00 [0.00, 0.00] | 372.68 [362.53, 382.83] | 372.68 [362.53, 382.83] |
| notification_failures | 0.00 [0.00, 0.00] | 7.76 [7.18, 8.34] | 7.76 [7.18, 8.34] |
| queue_order_violations | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |

## Scenario: emergency

Normal day plus two staff-entered emergency insertions per doctor.

Configuration: doctors=3, patients=24, planned_avg=10, mean_consult=10, cv=0.4, no_show=0.08, late_sd=6, late_start=(0, 0), breaks=0, emergencies=2, notify_fail=0.02

| Metric | Baseline | Smart OPD | Difference (Smart - Baseline) |
|---|---|---|---|
| eta_mae | 12.71 [11.85, 13.57] | 5.99 [5.79, 6.18] | -6.73 [-7.57, -5.88] |
| eta_median_ae | 9.89 [9.07, 10.72] | 4.09 [3.90, 4.28] | -5.80 [-6.62, -4.98] |
| eta_within_15 | 67.9% [65.0%, 70.8%] | 91.8% [91.0%, 92.5%] | 23.9% [21.2%, 26.6%] |
| wait_after_checkin | 19.03 [17.94, 20.12] | 12.12 [11.80, 12.45] | -6.91 [-7.83, -5.99] |
| eta_revisions | 0.00 [0.00, 0.00] | 15.64 [15.26, 16.02] | 15.64 [15.26, 16.02] |
| eta_revision_size | 0.00 [0.00, 0.00] | 5.56 [5.47, 5.66] | 5.56 [5.47, 5.66] |
| throughput_per_hour | 16.06 [15.87, 16.24] | 15.77 [15.58, 15.97] | -0.28 [-0.38, -0.19] |
| no_shows | 5.82 [5.37, 6.27] | 5.82 [5.37, 6.27] | 0.00 [0.00, 0.00] |
| skips | 5.83 [5.38, 6.28] | 6.06 [5.59, 6.53] | 0.23 [0.14, 0.32] |
| reinsertions | 0.01 [-0.01, 0.03] | 0.24 [0.15, 0.33] | 0.23 [0.14, 0.32] |
| notifications_sent | 0.00 [0.00, 0.00] | 196.80 [190.69, 202.91] | 196.80 [190.69, 202.91] |
| notification_failures | 0.00 [0.00, 0.00] | 3.85 [3.41, 4.29] | 3.85 [3.41, 4.29] |
| queue_order_violations | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |

## Scenario: notification_degradation

Normal day with half of all alerts failing.

Configuration: doctors=3, patients=24, planned_avg=10, mean_consult=10, cv=0.4, no_show=0.08, late_sd=6, late_start=(0, 0), breaks=0, emergencies=0, notify_fail=0.5

| Metric | Baseline | Smart OPD | Difference (Smart - Baseline) |
|---|---|---|---|
| eta_mae | 7.21 [6.82, 7.59] | 6.30 [5.98, 6.61] | -0.91 [-1.31, -0.51] |
| eta_median_ae | 6.02 [5.71, 6.34] | 3.98 [3.80, 4.15] | -2.05 [-2.33, -1.77] |
| eta_within_15 | 89.4% [87.6%, 91.2%] | 91.6% [90.8%, 92.4%] | 2.3% [0.6%, 3.9%] |
| wait_after_checkin | 10.42 [9.73, 11.10] | 10.21 [9.82, 10.60] | -0.21 [-0.65, 0.24] |
| eta_revisions | 0.00 [0.00, 0.00] | 14.33 [14.04, 14.61] | 14.33 [14.04, 14.61] |
| eta_revision_size | 0.00 [0.00, 0.00] | 5.33 [5.21, 5.44] | 5.33 [5.21, 5.44] |
| throughput_per_hour | 15.77 [15.60, 15.93] | 15.49 [15.30, 15.68] | -0.27 [-0.40, -0.14] |
| no_shows | 6.34 [5.88, 6.80] | 6.34 [5.88, 6.80] | 0.00 [0.00, 0.00] |
| skips | 6.35 [5.89, 6.81] | 7.77 [7.18, 8.36] | 1.42 [1.14, 1.70] |
| reinsertions | 0.01 [-0.01, 0.03] | 1.43 [1.15, 1.71] | 1.42 [1.14, 1.70] |
| notifications_sent | 0.00 [0.00, 0.00] | 171.89 [166.11, 177.67] | 171.89 [166.11, 177.67] |
| notification_failures | 0.00 [0.00, 0.00] | 87.05 [83.73, 90.37] | 87.05 [83.73, 90.37] |
| queue_order_violations | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |

## Scenario: stress

Higher volume with all disruptions combined.

Configuration: doctors=3, patients=36, planned_avg=10, mean_consult=11, cv=0.7, no_show=0.15, late_sd=10, late_start=(5, 25), breaks=1, emergencies=2, notify_fail=0.2

| Metric | Baseline | Smart OPD | Difference (Smart - Baseline) |
|---|---|---|---|
| eta_mae | 42.58 [39.54, 45.61] | 17.25 [16.22, 18.28] | -25.33 [-28.27, -22.38] |
| eta_median_ae | 39.05 [35.05, 43.04] | 9.42 [9.11, 9.73] | -29.63 [-33.57, -25.68] |
| eta_within_15 | 26.6% [23.7%, 29.5%] | 68.0% [66.8%, 69.3%] | 41.4% [38.6%, 44.3%] |
| wait_after_checkin | 50.68 [47.43, 53.94] | 18.86 [17.91, 19.82] | -31.82 [-34.77, -28.87] |
| eta_revisions | 0.00 [0.00, 0.00] | 33.72 [33.11, 34.34] | 33.72 [33.11, 34.34] |
| eta_revision_size | 0.00 [0.00, 0.00] | 8.63 [8.43, 8.83] | 8.63 [8.43, 8.83] |
| throughput_per_hour | 13.44 [13.22, 13.66] | 12.32 [12.08, 12.55] | -1.12 [-1.26, -0.98] |
| no_shows | 16.43 [15.65, 17.21] | 16.43 [15.65, 17.21] | 0.00 [0.00, 0.00] |
| skips | 16.68 [15.89, 17.47] | 21.97 [20.90, 23.04] | 5.29 [4.43, 6.15] |
| reinsertions | 0.25 [0.14, 0.36] | 5.54 [4.67, 6.41] | 5.29 [4.43, 6.15] |
| notifications_sent | 0.00 [0.00, 0.00] | 889.39 [864.91, 913.87] | 889.39 [864.91, 913.87] |
| notification_failures | 0.00 [0.00, 0.00] | 177.10 [171.57, 182.63] | 177.10 [171.57, 182.63] |
| queue_order_violations | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |

## Metric definitions

- **eta_mae**: Mean absolute error in minutes between the ETA shown at check-in and the simulated actual consultation start.
- **eta_median_ae**: Median absolute error, same pairing as eta_mae.
- **eta_within_15**: Share of patients whose ETA at check-in was within 15 minutes of the actual start.
- **wait_after_checkin**: Mean minutes between check-in and consultation start (physical waiting).
- **eta_revisions**: Mean number of times a patient's ETA changed by at least 1 minute while waiting.
- **eta_revision_size**: Mean absolute size in minutes of those ETA changes.
- **throughput_per_hour**: Consultations completed per hour from OPD opening to the last completion.
- **no_shows**: Mean patients per day who never arrived.
- **skips**: Mean skip actions per day (grace period ran out).
- **reinsertions**: Mean late arrivals reinserted after being skipped.
- **notifications_sent**: Mean alert attempts per day.
- **notification_failures**: Mean failed alert attempts per day.
- **queue_order_violations**: Times a patient was started while an earlier eligible patient waited. Should be 0.

## Limitations

Synthetic data is only as realistic as these assumptions. The model does not capture real human behaviour, clinical judgement, hospital-specific exceptions, connectivity or organisational constraints. Each doctor's queue is simulated independently, and patients always follow alerts that reach them. Results must be described as simulated outcomes (Appendix A6).
