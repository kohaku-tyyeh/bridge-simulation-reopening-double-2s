"""Audit saved final experiment outputs without rerunning DDS or auction Par."""

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean, stdev
import sys

from test_continuation_par import INITIAL, oracle_score, verify_line


def independent_imps(delta):
    # Inclusive upper endpoints from the standard IMP table.
    upper = [10, 40, 80, 120, 160, 210, 260, 310, 360, 420, 490, 590,
             740, 890, 1090, 1290, 1490, 1740, 1990, 2240, 2490, 2990,
             3490, 3990]
    absolute = abs(delta)
    magnitude = next((i for i, limit in enumerate(upper) if absolute <= limit), 24)
    return magnitude if delta >= 0 else -magnitude


def close(a, b):
    assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10), (a, b)


def audit(directory):
    directory = Path(directory)
    dataset = json.loads((directory / "deals.json").read_text())
    dds = [json.loads(s) for s in (directory / "dds.jsonl").read_text().splitlines()]
    rows = [json.loads(s) for s in (directory / "results.jsonl").read_text().splitlines()]
    summary = json.loads((directory / "summary.json").read_text())
    assert len(dataset["deals"]) == len(dds) == len(rows) == summary["n"] == 10000
    contracts, imp_counts, par_counts, outcome_counts = (Counter() for _ in range(4))
    tricks_groups = defaultdict(list)
    terminal_count = 0
    for number, (deal, table_record, row) in enumerate(zip(dataset["deals"], dds, rows), 1):
        assert deal["number"] == table_record["number"] == row["number"] == number
        pbn = "N:" + " ".join(".".join(deal["hands"][seat]["suits"][suit]
                                        for suit in "SHDC") for seat in "NESW")
        assert pbn == table_record["pbn"] == row["pbn"]
        assert row["handviewer_url"] == deal["handviewer_url"]
        table = table_record["dd_table_CDHSN_NESW"]
        assert len(table) == 5 and all(len(r) == 4 for r in table)
        assert all(isinstance(t, int) and 0 <= t <= 13 for r in table for t in r)
        assert row["east_2S_tricks"] == table[3][1]
        assert row["pass_score_ns"] == oracle_score(2, 3, 1, table[3][1])
        expected_delta = row["double_par_score_ns"] - row["pass_score_ns"]
        assert row["delta_ns"] == expected_delta
        assert row["delta_imp"] == independent_imps(expected_delta)
        assert row["bam_points"] == (1 if expected_delta > 0 else 0 if expected_delta < 0 else .5)
        terminal_set = set()
        assert row["optimal_contracts"]
        for c in row["optimal_contracts"]:
            level, strain, declarer, doubled = (c["level"], "CDHSN".index(c["strain"]),
                                                "NESW".index(c["declarer"]), c["doubled"])
            assert 1 <= level <= 7 and doubled in (0, 1, 2)
            bid = 5 * (level - 1) + strain
            assert bid >= 8
            if bid == 8:
                assert declarer == 1 and doubled >= 1
            if declarer % 2 == 1 and strain in (2, 3):
                assert declarer == 1
            if declarer % 2 == 0 and strain == 4:
                assert declarer == 0
            assert oracle_score(level, strain, declarer, table[strain][declarer], doubled) == row["double_par_score_ns"]
            terminal_set.add((level, strain, declarer, doubled))
            label = str(level) + c["strain"] + ("", "X", "XX")[doubled] + " " + c["declarer"]
            contracts[label] += 1
            terminal_count += 1
        assert len(terminal_set) == len(row["optimal_contracts"])
        c = row["representative_contract"]
        assert (c["level"], "CDHSN".index(c["strain"]), "NESW".index(c["declarer"]), c["doubled"]) in terminal_set
        numeric_actions = []
        for action in row["representative_continuation"]:
            if action in ("P", "X", "XX"):
                numeric_actions.append({"P": -1, "X": -2, "XX": -3}[action])
            else:
                numeric_actions.append((int(action[0]) - 1) * 5 + "CDHSN".index(action[1:]))
        verify_line(INITIAL, table, {"actions": numeric_actions,
                                    "score_ns": row["double_par_score_ns"],
                                    "contract": row["representative_contract"]})
        imp_counts[row["delta_imp"]] += 1
        par_counts[row["double_par_score_ns"]] += 1
        outcome_counts["win" if expected_delta > 0 else "loss" if expected_delta < 0 else "tie"] += 1
        tricks_groups[row["east_2S_tricks"]].append(row)

    assert dict(outcome_counts) == summary["bam_counts"]
    assert sum(outcome_counts.values()) == 10000
    for label, count in outcome_counts.items():
        close(count / 10000, summary["bam_proportions"][label])
    for field, key in (("delta_imp", "mean_imp"), ("delta_ns", "mean_raw_delta"),
                       ("bam_points", "bam_mean_points"), ("pass_score_ns", "mean_pass_score"),
                       ("double_par_score_ns", "mean_double_par_score")):
        close(fmean(row[field] for row in rows), summary[key])
    close((outcome_counts["win"] - outcome_counts["loss"]) / 10000, summary["bam_net_win_proportion"])
    assert {str(k): v for k, v in imp_counts.items()} == summary["imp_distribution"]
    assert {str(k): v for k, v in par_counts.items()} == summary["double_par_score_distribution"]
    assert {r["contract"]: r["count"] for r in summary["optimal_contract_occurrences"]} == dict(contracts)
    for c in summary["optimal_contract_occurrences"]:
        close(c["proportion"], c["count"] / 10000)
    assert sum(len(r["optimal_contracts"]) > 1 for r in rows) == summary["multiple_optimal_contract_deals"]
    for group in summary["grouped_by_undoubled_2S_tricks"]:
        records = tricks_groups[group["east_2S_tricks"]]
        assert len(records) == group["count"]
        assert sum(r["delta_ns"] > 0 for r in records) == group["wins"]
        assert sum(r["delta_ns"] == 0 for r in records) == group["ties"]
        assert sum(r["delta_ns"] < 0 for r in records) == group["losses"]
        close(fmean(r["delta_imp"] for r in records), group["mean_imp"])
    assert sorted(rows, key=lambda r: (-r["delta_imp"], -r["delta_ns"], r["number"]))[:3] == summary["representative_best"]
    assert sorted(rows, key=lambda r: (r["delta_imp"], r["delta_ns"], r["number"]))[:3] == summary["representative_worst"]
    assert dataset["rules"] == summary["rules"]
    for name, expected_hash in summary["source_sha256"].items():
        assert hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() == expected_hash

    wins = [r for r in rows if r["delta_ns"] > 0]
    losses = [r for r in rows if r["delta_ns"] < 0]
    report = {
        "status": "passed", "result_rows": 10000,
        "independently_scored_optimal_terminals": terminal_count,
        "legally_replayed_principal_variations": 10000,
        "dds_or_par_recomputed": False,
        "bam_counts": dict(outcome_counts), "bam_mean_points": summary["bam_mean_points"],
        "mean_imp": summary["mean_imp"], "mean_raw_delta": summary["mean_raw_delta"],
        "mean_imp_standard_error": stdev(r["delta_imp"] for r in rows) / 100,
        "wins_mean_imp": fmean(r["delta_imp"] for r in wins),
        "losses_mean_imp": fmean(r["delta_imp"] for r in losses),
        "raw_wins_but_zero_imp": sum(r["delta_imp"] == 0 for r in wins),
        "raw_losses_but_zero_imp": sum(r["delta_imp"] == 0 for r in losses),
        "source_hashes_match": True,
        "artifact_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                            for name in ("results.jsonl", "summary.json", "dds.jsonl")},
    }
    return report


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    report = audit(directory)
    (directory / "final_results_validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
