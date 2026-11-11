#!/usr/bin/env python3
"""Audit an East-only refinement of the agreed v4 bidding model.

This is a candidate family of filters, not a fitted bidding probability model.
The inclusive cohort retains all v4-accepted hands. The core cohort omits
specified style-sensitive cases, without declaring those auctions impossible.
Only East's cards and the public auction enter the refinement classification.
No DDS, Par, score, or actual partner holding is read by that classifier.
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

from filter_deals import (Hand, SUITS, POINTS, deal_failures, east_failures,
                          weak_four_card_hearts)


def features(hand):
    spades, hearts, diamonds, clubs = hand.suits
    weak_four_hearts = weak_four_card_hearts(hearts)
    return {
        "hcp": hand.hcp,
        "shape_SHDC": list(hand.shape),
        "basic_ltc": hand.losing_tricks,
        "suit_hcp_SHDC": [sum(POINTS.get(r, 0) for r in s) for s in hand.suits],
        "suit_ltc_SHDC": [sum(r not in s for r in "AKQ"[:len(s)]) for s in hand.suits],
        "major_AKQJT_counts": [len(set(s).intersection("AKQJT")) for s in (spades, hearts)],
        "short_minor_honors": [
            suit + rank for suit, ranks in zip("DC", (diamonds, clubs))
            if len(ranks) == 1 for rank in ranks if rank in "KQJ"
        ],
        "opening_1NT_candidate": (
            hand.shape == (5, 4, 2, 2)
            and 15 <= hand.hcp <= 17
            and all(set(s).intersection("AKQ") for s in (diamonds, clubs))
        ),
        "weak_four_hearts": weak_four_hearts,
        "prefer_2S_review": (
            weak_four_hearts and len(spades) == 6
            and len(set(spades).intersection("AKQJT")) >= 3
        ),
        "prefer_2C_review": (
            weak_four_hearts and len(clubs) >= 4
            and len(set(clubs).intersection("AKQJT")) >= 3
        ),
    }


def classify_east(hand, rules):
    f = features(hand)
    hard_failures = east_failures(hand, rules)
    boundary = []
    if f["opening_1NT_candidate"]:
        boundary.append("opening_1NT_style")
    # Extra high-card strength supplies a reason to bid even with poor hearts.
    # A weak four-card heart suit alone never changes core/boundary status.
    if f["prefer_2S_review"] and hand.hcp < 15:
        boundary.append("low_range_64_prefers_2S_with_weak_hearts")
    band = rules["opener_2H_hcp_by_major_lengths"].get(
        f"{hand.shape[0]}-{hand.shape[1]}"
    )
    if band is None and hand.shape[0] >= 6 and hand.shape[1] >= 5:
        boundary.append("longer_two_suiter_not_individually_agreed")
    # This is a review tag only. Preference does NOT guarantee a trump fit.
    pass_review = bool(
        band and hand.shape[0] >= 6 and hand.hcp >= band[1] - 1
        and hand.losing_tricks == 5
        and f["major_AKQJT_counts"][0] >= 3
    )
    return {
        "status": "excluded" if hard_failures else "boundary" if boundary else "core",
        "hard_failures": hard_failures,
        "boundary_reasons": boundary,
        "last_pass_review_only": pass_review,
        "features": f,
    }


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=Path, default=here / "run_10000/deals.json")
    parser.add_argument("--baseline-rules", type=Path, default=here / "model_v4_existing_sample/rules.json")
    parser.add_argument("--output", type=Path, default=here / "east_refinement_review")
    args = parser.parse_args()
    rules = json.loads(args.baseline_rules.read_text())
    data = json.loads(args.deals.read_text())
    counts = Counter()
    reason_counts = Counter()
    rows = []
    ids = {"core": [], "boundary": []}
    selected_examples = {6, 130, 1321, 8364, 9804}
    examples = []
    for d in data["deals"]:
        deal = {
            seat: Hand(tuple(d["hands"][seat]["suits"][suit] for suit in SUITS))
            for seat in "NESW"
        }
        if deal_failures(deal, rules):
            continue
        e = deal["E"]
        result = classify_east(e, rules)
        assert result["status"] != "excluded"
        ids[result["status"]].append(d["number"])
        counts[result["status"]] += 1
        reason_counts.update(result["boundary_reasons"])
        f = result["features"]
        for name in ("prefer_2S_review", "prefer_2C_review"):
            counts[name] += f[name]
        counts["last_pass_review_only"] += result["last_pass_review_only"]
        rows.append({
            "number": d["number"], "east_SHDC": "/".join(e.suits),
            "hcp": e.hcp, "basic_ltc": e.losing_tricks,
            "status": result["status"],
            "boundary_reasons": ";".join(result["boundary_reasons"]),
            "prefer_2S_review": f["prefer_2S_review"],
            "prefer_2C_review": f["prefer_2C_review"],
            "last_pass_review_only": result["last_pass_review_only"],
            "handviewer_url": d["handviewer_url"],
        })
        if d["number"] in selected_examples:
            examples.append({"number": d["number"], "east_SHDC": list(e.suits),
                             "handviewer_url": d["handviewer_url"], **result})
    assert set(ids["core"]).isdisjoint(ids["boundary"])
    summary = {
        "status": "candidate_unfitted_bidding_model",
        "inclusive_count": len(rows), "counts": dict(counts),
        "boundary_reason_counts_overlapping": dict(reason_counts),
        "baseline_rules": rules,
        "source_deals_sha256": hashlib.sha256(args.deals.read_bytes()).hexdigest(),
        "policy": {
            "inclusive": "All v4-accepted hands; no new hard exclusions.",
            "core": "v4-accepted hands with no boundary flag; a stricter sensitivity cohort, not a proven superior population.",
            "opening_1NT_candidate": "5422, 15-17 HCP, each minor doubleton contains A/K/Q; opening style unresolved.",
            "weak_four_hearts": "Diagnostic only: exactly four hearts, no A/K, and at most one of Q/J/T. Never exclude solely on this quality, especially at 15+ HCP.",
            "low_range_64": "Only below 15 HCP, exactly six spades and weak four hearts, with at least three AKQJT in spades, is 2S treated as the preferred alternative.",
            "last_pass": "Keep agreed basic LTC >= 5. Strong six-card spades at upper end of the band and five LTC are flagged for review only, never excluded by this tag.",
            "longer_two_suiters": "Keep under v4 provisional extension in inclusive cohort; outside core until separately specified.",
            "no_fitted_weights": True,
            "no_outcome_data_used": True,
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, obj in (("summary.json", summary), ("cohort_ids.json", ids), ("examples.json", examples)):
        (args.output / filename).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    with (args.output / "east_audit.csv").open("w", newline="") as out:
        if rows:
            writer = csv.DictWriter(out, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"inclusive": len(rows), "counts": dict(counts),
                      "boundary_reasons": dict(reason_counts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
