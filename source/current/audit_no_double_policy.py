#!/usr/bin/env python3
"""Independent audit for NS three-level suit no-double sensitivity runs.

Reads the original run and saved policy outputs. Does not change the source run
or invoke DDS/Par. Optional native-predicate checks inspect legality only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from test_continuation_par import INITIAL, advance, actions, oracle_score, terminal_score

SEATS, SUITS = "NESW", "CDHSN"


def records(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hands(pbn):
    dealer, data = pbn.split(":", 1)
    order = SEATS[SEATS.index(dealer):] + SEATS[:SEATS.index(dealer)]
    parsed = {seat: dict(zip("SHDC", hand.split("."))) for seat, hand in zip(order, data.split())}
    assert len(parsed) == 4 and all(sum(len(s) for s in h.values()) == 13 for h in parsed.values())
    assert all(sum(len(parsed[seat][suit]) for seat in SEATS) == 13 for suit in "SHDC")
    return parsed


def mask_for(pbn, policy):
    h = hands(pbn)
    allowed = {(2, 3)} if policy == "A" else {(2, 3), (1, 4)}
    return sum(1 << i for i, suit in enumerate("CDHS")
               if len(h["N"][suit]) + len(h["S"][suit]) == 8
               and tuple(sorted((len(h["E"][suit]), len(h["W"][suit])))) in allowed)


def imps(delta):
    inclusive = [10, 40, 80, 120, 160, 210, 260, 310, 360, 420, 490, 590,
                 740, 890, 1090, 1290, 1490, 1740, 1990, 2240, 2490, 2990, 3490, 3990]
    magnitude = next((i for i, upper in enumerate(inclusive) if abs(delta) <= upper), 24)
    return magnitude if delta >= 0 else -magnitude


def banned_double(state, mask):
    return (state.bid in range(10, 14) and state.doubled == 0
            and state.declarer in (0, 2) and state.next_player in (1, 3)
            and bool(mask & (1 << (state.bid % 5))))


def contract_tuple(c):
    return c["level"], c["strain"], c["declarer"], c["doubled"]


def parse_action(a):
    if isinstance(a, int):
        return {-1: "P", -2: "X", -3: "XX"}.get(a, a)
    if a in ("P", "X", "XX"):
        return a
    return (int(a[0]) - 1) * 5 + SUITS.index(a[1:])


def replay(row, dd, mask):
    state = INITIAL
    line = row["representative_continuation"]
    assert line, (row["number"], "missing PV")
    for i, raw in enumerate(line):
        action = parse_action(raw)
        assert action in list(actions(state)), (row["number"], i, state, action, "illegal bridge action")
        assert not (action == "X" and banned_double(state, mask)), (row["number"], i, "forbidden policy double")
        child = advance(state, action)
        if child is None:
            assert i == len(line) - 1, (row["number"], "actions after final pass")
            expected = (state.bid // 5 + 1, SUITS[state.bid % 5], SEATS[state.declarer], state.doubled)
            assert expected == contract_tuple(row["representative_contract"])
            assert terminal_score(state, dd) == row["double_par_score_ns"]
            return len(line)
        state = child
    raise AssertionError((row["number"], "PV did not terminate"))


def applicability(original):
    report = {}
    for policy in ("A", "B"):
        masks, strain, split, old_blocked = Counter(), Counter(), defaultdict(Counter), 0
        old_blocked_strains = Counter()
        for r in original:
            h, mask = hands(r["pbn"]), mask_for(r["pbn"], policy)
            masks[mask] += 1
            for i, s in enumerate("CDHS"):
                if mask & (1 << i):
                    strain[s] += 1
                    split[s][f"{len(h['E'][s])}-{len(h['W'][s])}"] += 1
            blocked = {c["strain"] for c in r["optimal_contracts"]
                       if c["level"] == 3 and c["strain"] in "CDHS"
                       and c["declarer"] in "NS" and c["doubled"] > 0
                       and mask & (1 << SUITS.index(c["strain"]))}
            old_blocked += bool(blocked)
            old_blocked_strains.update(blocked)
        report[policy] = {
            "any_eligible_strain_boards": len(original) - masks[0],
            "mask_frequency_CDHS_bits": dict(sorted(masks.items())),
            "eligible_strain_boards": {s: strain[s] for s in "CDHS"},
            "EW_ordered_splits": {s: dict(ct) for s, ct in split.items()},
            "old_cooptimal_sets_with_now_forbidden_terminal": old_blocked,
            "old_forbidden_terminal_presence_by_strain": dict(old_blocked_strains),
        }
    report["B_changes_mask_vs_A_boards"] = sum(mask_for(r["pbn"], "A") != mask_for(r["pbn"], "B") for r in original)
    report["note"] = "Eligibility counts are not counts of changed minimax values. Same-deal strain counts overlap."
    return report


def native_legality_check():
    import continuation_par_policy as native
    lib = native._library()
    count, blocked = 0, 0
    # This traverses all states relevant to action legality, including H/S masks
    # that never arise in this particular fixed-South sample.
    for bid in range(35):
        for decl in range(4):
            for next_player in range(4):
                for dbl in range(3):
                    for passes in range(3):
                        for mask in range(32):
                            # Include illegal same/lower bids and legal next/final bids.
                            for action in {-1, -2, -3, bid, bid + 1, 34, 35}:
                                if action == -1:
                                    expected = True
                                elif action == -2:
                                    expected = dbl == 0 and next_player % 2 != decl % 2
                                    prohibited = (10 <= bid <= 13 and decl % 2 == 0 and next_player % 2 == 1
                                                  and bool(mask & (1 << (bid % 5))))
                                    blocked += bool(expected and prohibited)
                                    expected = expected and not prohibited
                                elif action == -3:
                                    expected = dbl == 1 and next_player % 2 == decl % 2
                                else:
                                    expected = bid < action < 35
                                actual = bool(lib.cp_policy_is_legal(bid, decl, dbl, passes, next_player, action, mask))
                                assert actual == expected, (bid, decl, next_player, dbl, passes, mask, action)
                                count += 1
    return {"checked_state_actions": count, "forbidden_double_cases": blocked, "status": "passed",
            "includes_all_strains_all_masks_NT_bit_and_all_levels": True,
            "solver_recomputed": False}


def audit_scenario(original, dd_by_id, path, policy):
    path = Path(path)
    rows = records(path / "results.jsonl" if path.is_dir() else path)
    assert len(rows) == len(original)
    by_id = {r["number"]: r for r in rows}
    assert len(by_id) == len(rows)
    zero_mask, changed, terminals, pv_calls = 0, 0, 0, 0
    imp_ct, par_ct, outcomes, presence = Counter(), Counter(), Counter(), Counter()
    for baseline in original:
        r = by_id[baseline["number"]]
        n = r["number"]
        dd_record = dd_by_id[n]
        assert r["pbn"] == baseline["pbn"] == dd_record["pbn"]
        table = dd_record["dd_table_CDHSN_NESW"]
        mask = mask_for(r["pbn"], policy)
        for key in ("blocked_ns_level3_strains", "blocked_strains_mask", "mask"):
            if key in r:
                assert r[key] == mask, (policy, n, key, r[key], mask)
        assert r["east_2S_tricks"] == baseline["east_2S_tricks"] == table[3][1]
        assert r["pass_score_ns"] == baseline["pass_score_ns"] == oracle_score(2, 3, 1, table[3][1])
        assert r["double_par_score_ns"] >= baseline["double_par_score_ns"], (policy, n, "monotonic Par")
        delta = r["double_par_score_ns"] - r["pass_score_ns"]
        assert r["delta_ns"] == delta
        assert r["delta_imp"] == imps(delta)
        assert r["delta_imp"] >= baseline["delta_imp"]
        assert r["bam_points"] == (1 if delta > 0 else 0 if delta < 0 else .5)
        assert r["bam_points"] >= baseline["bam_points"]
        cs = {contract_tuple(c) for c in r["optimal_contracts"]}
        assert cs and len(cs) == len(r["optimal_contracts"])
        assert contract_tuple(r["representative_contract"]) in cs
        for level, s, seat, doubled in cs:
            strain, declarer = SUITS.index(s), SEATS.index(seat)
            assert 1 <= level <= 7 and doubled in (0, 1, 2)
            bid = (level - 1) * 5 + strain
            assert bid >= 8
            if bid == 8:
                assert seat == "E" and doubled in (1, 2)
            if seat in "EW" and s in "HS":
                assert seat == "E"
            if seat in "NS" and s == "N":
                assert seat == "N"
            assert not (level == 3 and s in "CDHS" and seat in "NS" and doubled > 0 and mask & (1 << strain)), (policy, n, "forbidden terminal")
            assert oracle_score(level, strain, declarer, table[strain][declarer], doubled) == r["double_par_score_ns"]
            terminals += 1
        if mask == 0:
            assert r["double_par_score_ns"] == baseline["double_par_score_ns"]
            assert cs == {contract_tuple(c) for c in baseline["optimal_contracts"]}, (policy, n, "mask zero contract set changed")
            zero_mask += 1
        changed += r["double_par_score_ns"] != baseline["double_par_score_ns"]
        pv_calls += replay(r, table, mask)
        imp_ct[r["delta_imp"]] += 1
        par_ct[r["double_par_score_ns"]] += 1
        outcomes["win" if delta > 0 else "loss" if delta < 0 else "tie"] += 1
        presence.update({("NS" if c[2] in "NS" else "EW", c[0], c[1], c[3]) for c in cs})
    total = len(rows)
    stat = {
        "status": "passed", "policy": policy, "n": total,
        "legally_replayed_principal_variations": total, "replayed_calls": pv_calls,
        "independently_scored_optimal_terminals": terminals,
        "zero_mask_full_contract_sets_identical": zero_mask,
        "par_score_improved_vs_original_boards": changed,
        "mean_imp": sum(r["delta_imp"] for r in rows) / total,
        "sum_imp": sum(r["delta_imp"] for r in rows),
        "mean_raw_delta": sum(r["delta_ns"] for r in rows) / total,
        "mean_double_par_score": sum(r["double_par_score_ns"] for r in rows) / total,
        "mean_pass_score": sum(r["pass_score_ns"] for r in rows) / total,
        "bam_mean_points": sum(r["bam_points"] for r in rows) / total,
        "bam_counts": dict(outcomes),
        "loss8": sum(r["delta_imp"] <= -8 for r in rows),
        "loss10": sum(r["delta_imp"] <= -10 for r in rows),
        "gain8": sum(r["delta_imp"] >= 8 for r in rows),
        "imp_positive": sum(r["delta_imp"] > 0 for r in rows),
        "imp_zero": sum(r["delta_imp"] == 0 for r in rows),
        "imp_negative": sum(r["delta_imp"] < 0 for r in rows),
        "imp_distribution": dict(sorted(imp_ct.items())),
        "par_score_distribution": dict(sorted(par_ct.items())),
        "dds_or_par_recomputed": False,
    }
    summary_file = (path if path.is_dir() else path.parent) / "summary.json"
    if summary_file.exists():
        summary = json.loads(summary_file.read_text())
        if "scenarios" in summary:
            summary = summary["scenarios"]["protect_32" if policy == "A" else "protect_32_41"]
        for key in ("n", "mean_imp", "sum_imp", "mean_raw_delta", "bam_mean_points", "mean_double_par_score",
                    "mean_pass_score", "loss8", "loss10", "gain8", "imp_positive", "imp_zero", "imp_negative"):
            if key in summary:
                assert math.isclose(summary[key], stat[key], rel_tol=1e-12, abs_tol=1e-10), (policy, key)
        for key in ("bam_counts", "imp_distribution", "par_score_distribution"):
            if key in summary:
                assert {str(k): v for k, v in summary[key].items()} == {str(k): v for k, v in stat[key].items()}
    return stat, by_id


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("--scenario-a", type=Path)
    ap.add_argument("--scenario-b", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--native-legality", action="store_true")
    args = ap.parse_args()
    source = args.source.resolve()
    protected = {source / name for name in ("results.jsonl", "dds.jsonl", "summary.json", "deals.json")}
    assert args.output.resolve() not in protected, "Do not overwrite original run input files"
    original = records(source / "results.jsonl")
    dds = records(source / "dds.jsonl")
    assert len(original) == len(dds) == 10000
    dd_by_id = {r["number"]: r for r in dds}
    assert len(dd_by_id) == 10000
    result = {"source": str(source), "n": len(original), "applicability": applicability(original),
              "source_sha256": {f: digest(source / f) for f in ("results.jsonl", "dds.jsonl", "summary.json", "deals.json")}}
    if args.native_legality:
        result["native_legality"] = native_legality_check()
    output_rows = {}
    for policy, path in [("A", args.scenario_a), ("B", args.scenario_b)]:
        if path:
            result[policy], output_rows[policy] = audit_scenario(original, dd_by_id, path, policy)
    if set(output_rows) == {"A", "B"}:
        changed = 0
        for n, a in output_rows["A"].items():
            b = output_rows["B"][n]
            for key in ("double_par_score_ns", "delta_imp", "bam_points"):
                assert b[key] >= a[key], (n, key, "B must not worsen NS")
            if mask_for(a["pbn"], "A") == mask_for(a["pbn"], "B"):
                assert a["double_par_score_ns"] == b["double_par_score_ns"]
                assert {contract_tuple(c) for c in a["optimal_contracts"]} == {contract_tuple(c) for c in b["optimal_contracts"]}
            changed += b["double_par_score_ns"] != a["double_par_score_ns"]
        result["B_vs_A"] = {"pointwise_monotonicity_passed": True, "score_improved_boards": changed}
    for name, expected in result["source_sha256"].items():
        assert digest(source / name) == expected, (name, "source mutated during audit")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
