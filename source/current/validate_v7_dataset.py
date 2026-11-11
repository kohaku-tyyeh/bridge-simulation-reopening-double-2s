"""Independent checks of the continued v7 dataset, without production filter imports.

Only saved cards, auction, rule configuration and generation metadata are used.
DDS and Par outcomes are neither read nor recomputed.
"""

import argparse
import csv
from collections import Counter
from fractions import Fraction
from functools import lru_cache
import hashlib
import math
import random
import time
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

RANKS = "AKQJT98765432"
SUITS = "SHDC"
SEATS = "NESW"
DECK = {s + r for s in SUITS for r in RANKS}


HCP = {"A": 4, "K": 3, "Q": 2, "J": 1}
FOUR_THRESHOLD = Fraction(113, 20)
FIVE_THRESHOLD = Fraction(25, 4)


@lru_cache(maxsize=None)
def independent_knr(cards):
    """Exact rational full contribution of one four/five-card suit.

    Reimplements Pavlicek steps 1--23 from ordinary point values, without
    importing the production evaluator. Whole-hand corrections are excluded.
    Length scales the quality component, not the high-card component.
    """
    if len(cards) not in (4, 5) or len(set(cards)) != len(cards):
        raise ValueError("Expected four or five distinct ranks")
    if any(rank not in RANKS for rank in cards):
        raise ValueError("Invalid rank")
    higher_than_ten = sum(rank in cards for rank in "AKQJ")
    top_five_count = higher_than_ten + ("T" in cards)
    quality = Fraction(sum(HCP.get(rank, 0) for rank in cards))
    if "T" in cards:
        quality += Fraction(1, 2)
        if "J" in cards or higher_than_ten >= 2:
            quality += Fraction(1, 2)
    if "9" in cards:
        if "8" in cards or "T" in cards or top_five_count == 2:
            quality += Fraction(1, 2)
        # Step 8 requires absence of BOTH eight and ten.
        if "8" not in cards and "T" not in cards and higher_than_ten == 3:
            quality += Fraction(1, 2)
    high_cards = Fraction(3 * ("A" in cards) + 2 * ("K" in cards))
    if "Q" in cards:
        high_cards += Fraction(1) if ("A" in cards or "K" in cards) else Fraction(3, 4)
    if "J" in cards:
        above_jack = sum(rank in cards for rank in "AKQ")
        if above_jack == 2:
            high_cards += Fraction(1, 2)
        elif above_jack == 1:
            high_cards += Fraction(1, 4)
    if "T" in cards:
        if higher_than_ten == 2:
            high_cards += Fraction(1, 4)
        if "9" in cards and higher_than_ten == 1:
            high_cards += Fraction(1, 4)
    return quality * Fraction(len(cards), 10) + high_cards


def qualifying_four(spades, total_hcp, side_high_control):
    return (len(spades) == 4 and total_hcp >= 8 and side_high_control
            and independent_knr(spades) >= FOUR_THRESHOLD)


def penalty_branches(spades, total_hcp, side_high_control):
    """Return independent v6 branch flags; inheritance projects HCP as well."""
    four = qualifying_four(spades, total_hcp, side_high_control)
    ordinary_five = inherited_four = False
    if len(spades) == 5:
        control_exception = "A" in spades or ("K" in spades and "Q" in spades)
        ordinary_five = (independent_knr(spades) >= FIVE_THRESHOLD
                         and (total_hcp >= 8 or (total_hcp >= 7 and control_exception)))
        inherited_four = any(
            qualifying_four(spades[:i] + spades[i + 1:],
                            total_hcp - HCP.get(deleted, 0), side_high_control)
            for i, deleted in enumerate(spades)
        )
    return {"four_knr": bool(four), "five_knr": bool(ordinary_five),
            "five_inherits_four": bool(inherited_four)}


def best_four_knr(spades):
    if len(spades) != 5:
        return None
    return max(independent_knr(spades[:i] + spades[i + 1:]) for i in range(5))


def same_optional_score(actual, expected):
    if expected is None:
        return actual is None
    return (isinstance(actual, (int, float)) and not isinstance(actual, bool)
            and math.isclose(actual, float(expected), rel_tol=0, abs_tol=1e-10))


def formula_self_checks():
    anchors = {"KQT2": "5.65", "KQT52": "6.25", "AJT2": "5.9", "AJT52": "6.5",
               "AQ52": "6.4", "AQ542": "7.0", "QT764": "2.0"}
    for holding, expected in anchors.items():
        assert independent_knr(holding) == Fraction(expected), (holding, expected)
    assert qualifying_four("KQT2", 8, True)
    assert not qualifying_four("KQT2", 7, True)
    assert not qualifying_four("KQT2", 8, False)
    assert penalty_branches("KQT52", 7, False)["five_knr"]
    assert not any(penalty_branches("KQT52", 6, False).values())
    assert penalty_branches("AJT52", 7, False)["five_knr"]
    assert penalty_branches("KQJ52", 7, False)["five_knr"]
    assert penalty_branches("KQT52", 8, False)["five_knr"]
    # Removing an honor must reduce projected HCP, although a spot deletion
    # can separately inherit. The two suit lengths must be evaluated afresh.
    assert independent_knr("KQT52") != independent_knr("KQT2")
    assert best_four_knr("KQT52") == FOUR_THRESHOLD
    assert not qualifying_four("AKQ2", 8 - HCP["J"], True)
    return len(anchors)


def check_rule_configuration(rules):
    """Reject a mislabeled configuration rather than silently relaxing v6."""
    expected = {
        "model_version": 7, "penalty_min_hcp": 8,
        "partner_nt_minor_choice_filter": True,
        "penalty_four_min_knr": 5.65, "penalty_five_min_knr": 6.25,
        "penalty_five_control_min_hcp": 7, "penalty_five_inherits_four": True,
        "penalty_four_spades_side_honors": ["K", "A"],
        "opener_min_hcp": 11, "opener_max_hcp": 17,
        "opener_min_losing_tricks": 5,
        "opener_excluded_major_lengths_for_2H": [[7, 4]],
        "opener_2H_hcp_by_major_lengths": {"5-4": [15, 17], "5-5": [13, 16],
                                           "6-4": [13, 16], "6-5": [11, 15]},
        "opener_2H_longer_two_suiter_hcp": [11, 15],
        "opener_2H_weak_hearts_policy": {"mode": "review_only", "extra_values_hcp": 15,
                                        "alternative_spade_length": 6, "alternative_spade_top5_min": 3},
        "partner_nt_min_hcp": 6, "partner_nt_max_hcp": 10,
        "partner_max_hearts": 3, "partner_min_suit_length": 2, "partner_max_suit_length": 5,
        "responder_max_spades": 4, "responder_2S_max_hcp": 7,
        "responder_0_2_spades_max_hcp": 9, "responder_balanced_3_spades_max_hcp": 5,
        "responder_other_support_max_hcp": 4, "preference_requires_spades_ge_hearts": True,
    }
    for key, value in expected.items():
        assert rules.get(key) == value, ("v7 configuration mismatch", key, rules.get(key), value)


PROVENANCE_FIELDS = {"number", "source_run", "source_number", "source_shuffle_index"}


def independent_nt_choice_reject(suits):
    """Evaluate the approved North 1NT-choice rule from cards alone."""
    spades = suits["S"]
    minors = [suits[suit] for suit in ("C", "D") if len(suits[suit]) == 5]
    if not minors:
        return False
    has_exception = ("A" in spades or ("K" in spades and "Q" in spades)
                     or (len(spades) >= 4 and "Q" in spades and "J" in spades))
    if has_exception:
        return False
    total_hcp = sum(HCP.get(rank, 0) for holding in suits.values() for rank in holding)
    low_hcp = 6 <= total_hcp <= 8
    five_four_two_two = tuple(sorted(map(len, suits.values()), reverse=True)) == (5, 4, 2, 2)
    concentrated_minor = any(sum(rank in holding for rank in "AKQJ") >= 2 for holding in minors)
    return low_hcp or five_four_two_two or concentrated_minor


def nt_choice_self_checks():
    examples = [(("J965", "Q2", "92", "KQJ32"), True),
                (("Q86", "Q6", "543", "KQJ98"), True),
                (("K862", "83", "92", "QJT98"), True),
                (("AQ8", "863", "92", "KJT93"), False)]
    for cards, rejected in examples:
        assert independent_nt_choice_reject(dict(zip(SUITS, cards))) == rejected
    return len(examples)


def identity_of(record):
    return tuple(tuple(record["hands"][seat]["suits"][suit] for suit in SUITS) for seat in SEATS)


def pbn_of(record):
    return "N:" + " ".join(".".join(record["hands"][seat]["suits"][suit] for suit in SUITS) for seat in SEATS)


def same_original_content(record, source):
    return ({k: v for k, v in record.items() if k not in PROVENANCE_FIELDS}
            == {k: v for k, v in source.items() if k not in PROVENANCE_FIELDS})


def checkpoint_pbn(unknown):
    fixed = {"S": "3", "H": "9754", "D": "AKT8", "C": "A764"}
    fixed_ids = {13 * SUITS.index(suit) + RANKS.index(rank)
                 for suit, holding in fixed.items() for rank in holding}
    assert len(unknown) == len(set(unknown)) == 39
    assert set(unknown) == set(range(52)) - fixed_ids
    holdings = {"S": fixed}
    for seat, cards in (("E", unknown[:13]), ("N", unknown[13:26]), ("W", unknown[26:])):
        ordered = sorted(cards)
        holdings[seat] = {suit: "".join(RANKS[c % 13] for c in ordered if c // 13 == j)
                          for j, suit in enumerate(SUITS)}
    return "N:" + " ".join(".".join(holdings[seat][suit] for suit in SUITS) for seat in SEATS)


def random_state_tuple(saved):
    assert len(saved) == 3 and saved[0] == 3 and saved[2] is None
    assert len(saved[1]) == 625
    assert all(isinstance(x, int) and 0 <= x <= 2 ** 32 - 1 for x in saved[1][:-1])
    assert 0 <= saved[1][-1] <= 624
    return saved[0], tuple(saved[1]), saved[2]


def check_sampling_and_mapping(data, source, directory):
    manifest_path = directory / "sampling_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest == data["sampling"]
    assert len(source["deals"]) == manifest["source_accepted"] == 10000
    assert source["seed"] == data["seed"] == manifest["seed"] == 2026111108
    assert source["attempts"] == manifest["source_attempts"] == 20577853
    assert manifest["additional_attempts"] > 0
    assert manifest["total_stream_attempts"] == data["attempts"] == source["attempts"] + manifest["additional_attempts"]
    assert manifest["replayed_shuffles_are_not_new_attempts"] is True
    assert manifest["source_rejection_counts_not_reclassified"] is True
    original_kept = [r for r in source["deals"] if not independent_nt_choice_reject(r["hands"]["N"]["suits"])]
    assert len(original_kept) == manifest["source_retained"] == 9128
    assert len(source["deals"]) - len(original_kept) == manifest["source_rejected_by_new_rule"] == 872
    new_records = data["deals"][len(original_kept):]
    assert len(new_records) == manifest["additional_accepted"] == 872
    reasons = manifest["additional_rejection_first_reason_counts"]
    assert all(isinstance(n, int) and n >= 0 for n in reasons.values())
    assert sum(reasons.values()) + len(new_records) == manifest["additional_attempts"]
    # Source rules are unchanged apart from the expressly approved additions.
    comparable = lambda r: {k: v for k, v in r.items()
                            if k not in ("model_version", "notes", "partner_nt_minor_choice_filter")}
    assert source["rules"]["model_version"] == 6 and comparable(source["rules"]) == comparable(data["rules"])
    for final, original in zip(data["deals"][:9128], original_kept):
        assert final["source_run"] == "run_v6_10000"
        assert final["source_number"] == original["number"]
        assert "source_shuffle_index" not in final
        assert same_original_content(final, original), (final["number"], "retained source content changed")
    source_ids = {identity_of(r) for r in source["deals"]}
    assert len(source_ids) == 10000
    previous_index = source["attempts"]
    for i, final in enumerate(new_records, 1):
        assert final["number"] == 9128 + i
        assert final["source_run"] == "v7_supplement" and final["source_number"] == i
        index = final["source_shuffle_index"]
        assert previous_index < index <= data["attempts"]
        assert identity_of(final) not in source_ids, (i, "new deal overlaps source")
        previous_index = index
    assert previous_index == data["attempts"], "Sampling must stop on the final accepted shuffle"
    final_ids = {identity_of(r) for r in data["deals"]}
    overlap = len(final_ids & source_ids)
    assert overlap == 9128
    assert final_ids & source_ids == {identity_of(r) for r in original_kept}
    supplement = json.loads((directory / "supplement/deals.json").read_text())
    assert supplement["deals"] == new_records
    assert supplement["attempts"] == manifest["additional_attempts"]
    for key in ("seed", "rules", "dealer", "vulnerability", "next_to_act", "auction", "sampling"):
        assert supplement[key] == data[key]
    with (directory / "provenance.csv").open(newline="") as stream:
        mapping = list(csv.DictReader(stream))
    assert len(mapping) == 10000
    for row, record in zip(mapping, data["deals"]):
        for key in ("number", "source_run", "source_number", "source_shuffle_index"):
            assert row[key] == str(record.get(key, ""))
    return manifest, new_records, {"source_retained": 9128, "source_rejected": 872,
                                   "new_deals": 872, "source_overlap": overlap,
                                   "all_retained_content_identical": True,
                                   "all_new_deals_disjoint_from_all_source_deals": True,
                                   "provenance_csv_rows_verified": len(mapping)}


def check_rng_lineage(directory, source, new_records, manifest):
    before_path, after_path = directory / "rng_after_v6.json", directory / "rng_checkpoint.json"
    before, after = (json.loads(p.read_text()) for p in (before_path, after_path))
    assert before["seed"] == after["seed"] == manifest["seed"]
    assert before["attempts"] == source["attempts"]
    assert before["last_v6_deal_verified"] is True
    assert checkpoint_pbn(before["unknown_deck"]) == pbn_of(source["deals"][-1])
    assert after["attempts"] == manifest["total_stream_attempts"]
    assert after["accepted_final_count"] == 10000
    assert after["last_pbn"] == checkpoint_pbn(after["unknown_deck"]) == pbn_of(new_records[-1])
    rng = random.Random()
    rng.setstate(random_state_tuple(before["random_state"]))
    expected_final_state = random_state_tuple(after["random_state"])
    unknown = list(before["unknown_deck"])
    positions = {r["source_shuffle_index"] - source["attempts"]: pbn_of(r) for r in new_records}
    assert len(positions) == len(new_records) == 872
    checked = 0
    started = time.monotonic()
    for index in range(1, manifest["additional_attempts"] + 1):
        rng.shuffle(unknown)
        if index in positions:
            assert checkpoint_pbn(unknown) == positions[index], (index, "saved accepted deal mismatches RNG continuation")
            checked += 1
    assert checked == 872
    assert unknown == after["unknown_deck"]
    assert rng.getstate() == expected_final_state
    return {"status": "passed", "source_boundary_deal_verified": True,
            "old_prefix_shuffles_replayed_by_this_validator": 0,
            "additional_shuffles_replayed": manifest["additional_attempts"],
            "accepted_shuffle_positions_verified": checked,
            "final_deck_and_random_state_match": True,
            "replay_seconds": time.monotonic() - started,
            "note": "Replays saved shuffle positions; does not recompute all rejected-deal reason labels or the old 20M-shuffle prefix.",
            "checkpoint_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (before_path, after_path)}}


def check(path, source_path=None, expected_count=10000, expected_seed=2026111108):
    path = Path(path)
    directory = path.parent
    source_path = Path(source_path) if source_path else directory.parent / "run_v6_10000/deals.json"
    source_raw = source_path.read_bytes()
    source = json.loads(source_raw)
    raw = path.read_bytes()
    data = json.loads(raw)
    rules = data["rules"]
    check_rule_configuration(rules)
    formula_anchor_count = formula_self_checks()
    choice_anchor_count = nt_choice_self_checks()
    quality = rules["opener_2H_weak_hearts_policy"]
    assert quality["extra_values_hcp"] == 15
    assert quality["mode"] == "review_only"
    assert len(data["deals"]) == expected_count
    if expected_seed is not None:
        assert data["seed"] == expected_seed
    assert data["dealer"] == "N" and data["vulnerability"] == "EW"
    assert data["next_to_act"] == "S"
    assert data["auction"] == ["P", "1S", "D", "P", "1N", "2H", "P", "2S", "P", "P"]
    assert expected_count == 10000
    manifest, new_records, provenance = check_sampling_and_mapping(data, source, directory)
    seen = set()
    east_hcp, east_ltc, east_shapes, north_hcp, north_spades = (Counter() for _ in range(5))
    diagnostic_counts = Counter()
    north_knr_by_spade_length = {4: Counter(), 5: Counter()}
    for number, record in enumerate(data["deals"], 1):
        assert record["number"] == number
        cards, hp, shapes, ltc = [], {}, {}, {}
        hands = record["hands"]
        for seat in SEATS:
            suits = hands[seat]["suits"]
            assert set(suits) == set(SUITS)
            hand = []
            for suit in SUITS:
                holding = suits[suit]
                assert all(rank in RANKS for rank in holding)
                assert holding == "".join(sorted(holding, key=RANKS.index))
                hand.extend(suit + rank for rank in holding)
            assert len(hand) == 13 and len(set(hand)) == 13
            cards.extend(hand)
            hp[seat] = sum({"A": 4, "K": 3, "Q": 2, "J": 1}.get(c[1], 0) for c in hand)
            shapes[seat] = tuple(len(suits[suit]) for suit in SUITS)
            ltc[seat] = sum(min(3, len(holding))
                            - sum(honor in holding for honor in "AKQ"[:min(3, len(holding))])
                            for holding in suits.values())
            balanced = tuple(sorted(shapes[seat], reverse=True)) in ((4, 3, 3, 3), (4, 4, 3, 2), (5, 3, 3, 2))
            assert hp[seat] == hands[seat]["hcp"]
            assert list(shapes[seat]) == hands[seat]["shape_SHDC"]
            assert ltc[seat] == hands[seat]["basic_ltc"]
            assert balanced == hands[seat]["balanced"]
        assert len(cards) == len(set(cards)) == 52 and set(cards) == DECK
        assert sum(hp.values()) == 40 and hp["N"] + hp["E"] + hp["W"] == 29
        assert hands["S"]["suits"] == {"S": "3", "H": "9754", "D": "AKT8", "C": "A764"}
        identity = tuple(tuple(hands[seat]["suits"][suit] for suit in SUITS) for seat in SEATS)
        assert identity not in seen
        seen.add(identity)

        es, eh, _, _ = shapes["E"]
        assert rules["opener_min_hcp"] <= hp["E"] <= rules["opener_max_hcp"]
        assert es >= 5 and eh >= 4 and es >= eh
        assert [es, eh] not in rules["opener_excluded_major_lengths_for_2H"]
        band = rules["opener_2H_hcp_by_major_lengths"].get(f"{es}-{eh}")
        if band is None and es >= 6 and eh >= 5:
            band = rules["opener_2H_longer_two_suiter_hcp"]
        assert band is not None and band[0] <= hp["E"] <= band[1]
        assert ltc["E"] >= rules["opener_min_losing_tricks"]
        # Reimplement the action-choice exception independently. At 15+ HCP
        # weak hearts alone never disqualify the natural 2H continuation.
        hearts_e, spades_e = hands["E"]["suits"]["H"], hands["E"]["suits"]["S"]
        too_weak_to_prefer_hearts = (
            eh == 4 and "A" not in hearts_e and "K" not in hearts_e
            and sum(rank in hearts_e for rank in "QJT") <= 1
        )
        stronger_spade_rebid_available = (
            es == quality["alternative_spade_length"]
            and sum(rank in spades_e for rank in "AKQJT") >= quality["alternative_spade_top5_min"]
        )
        diagnostic_counts["weak_four_hearts_at_least_15_hcp_retained"] += (
            hp["E"] >= quality["extra_values_hcp"] and too_weak_to_prefer_hearts)
        diagnostic_counts["low_range_64_spade_alternative_retained"] += (
            hp["E"] < quality["extra_values_hcp"]
            and too_weak_to_prefer_hearts and stronger_spade_rebid_available)
        diagnostic_counts["opening_1NT_style_candidates_retained"] += (
            shapes["E"] == (5, 4, 2, 2) and 15 <= hp["E"] <= 17
            and all(any(rank in hands["E"]["suits"][suit] for rank in "AKQ")
                    for suit in "DC"))

        assert not independent_nt_choice_reject(hands["N"]["suits"]), (number, "North new 1NT-choice exclusion")
        ns, nh, _, _ = shapes["N"]
        spades = hands["N"]["suits"]["S"]
        assert rules["partner_nt_min_hcp"] <= hp["N"] <= rules["partner_nt_max_hcp"]
        assert nh <= rules["partner_max_hearts"]
        assert min(shapes["N"]) >= rules["partner_min_suit_length"]
        assert max(shapes["N"]) <= rules["partner_max_suit_length"]
        assert ("A" in spades or ("K" in spades and ns >= 2)
                or ("Q" in spades and ns >= 3) or ("J" in spades and ns >= 4))
        floor = max([0] + [2 * sum(r in spades for r in RANKS[:k]) - k for k in range(1, 14)])
        side_high_control = any(rank in hands["N"]["suits"][suit]
                                for suit in "HDC" for rank in "AK")
        branches = penalty_branches(spades, hp["N"], side_high_control)
        assert not any(branches.values()), (number, "North would proactively double", branches)
        own_knr = independent_knr(spades) if ns in (4, 5) else None
        best_four = best_four_knr(spades)
        recorded = record["north_penalty_check"]
        assert set(recorded) == {"spade_promotion_floor", "spade_knr_points",
                                 "best_four_spade_knr_points", "penalty_reason"}
        assert recorded["spade_promotion_floor"] == floor
        assert recorded["penalty_reason"] is None
        assert same_optional_score(recorded["spade_knr_points"], own_knr), (number, "spade KnR metadata")
        assert same_optional_score(recorded["best_four_spade_knr_points"], best_four), (number, "best-four KnR metadata")
        if own_knr is not None:
            north_knr_by_spade_length[ns][f"{float(own_knr):.2f}"] += 1

        ws, wh, _, _ = shapes["W"]
        assert ws <= rules["responder_max_spades"]
        assert not rules["preference_requires_spades_ge_hearts"] or ws >= wh
        max_hcp = (rules["responder_0_2_spades_max_hcp"] if ws <= 2
                   else rules["responder_balanced_3_spades_max_hcp"]
                   if ws == 3 and hands["W"]["balanced"]
                   else rules["responder_other_support_max_hcp"])
        assert hp["W"] <= max_hcp
        assert hp["W"] <= rules["responder_2S_max_hcp"]

        q = {k: v[0] for k, v in parse_qs(urlsplit(record["handviewer_url"]).query).items()}
        assert q["d"] == "n" and q["v"] == "e" and q["a"] == "p1sdp1n2hp2spp"
        assert "i" not in q
        for seat in SEATS:
            expected = "".join(s + hands[seat]["suits"][s] for s in SUITS).lower()
            assert q[seat.lower()] == expected
        east_hcp[hp["E"]] += 1
        east_ltc[ltc["E"]] += 1
        east_shapes["-".join(map(str, shapes["E"]))] += 1
        north_hcp[hp["N"]] += 1
        north_spades[ns] += 1

    rng_validation = check_rng_lineage(directory, source, new_records, manifest)
    assert hashlib.sha256(source_path.read_bytes()).digest() == hashlib.sha256(source_raw).digest()
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(raw).digest()

    return {
        "status": "passed", "deals_checked": expected_count, "unique_deals": len(seen),
        "sha256": hashlib.sha256(raw).hexdigest(), "seed": data["seed"],
        "attempts": data["attempts"], "additional_attempts": manifest["additional_attempts"],
        "source_sha256": hashlib.sha256(source_raw).hexdigest(),
        "source_path": str(source_path), "provenance": provenance,
        "rng_validation": rng_validation, "nt_choice_anchor_cases": choice_anchor_count,
        "dds_or_par_used": False, "production_filter_imported": False,
        "independent_knr_formula_anchors": formula_anchor_count,
        "north_knr_by_spade_length": {str(k): dict(sorted(v.items(), key=lambda pair: float(pair[0])))
                                       for k, v in north_knr_by_spade_length.items()},
        "east_review_only_diagnostics": dict(diagnostic_counts),
        "previous_dataset_overlap": provenance["source_overlap"],
        "checks": ["52 unique legal cards", "fixed South", "40 total HCP", "29 unknown HCP",
                   "all bidding-model rules independently evaluated", "recorded metadata recomputed",
                   "exact-rational four/five-card KnR and delete-one projected HCP",
                   "legacy promotion floor diagnostic only",
                   "all Handviewer cards/auction/vulnerability", "generation accounting",
                   "independent North 1NT-choice exclusion", "9128 source records retained exactly",
                   "872 supplemental deals distinct from source", "source mapping and supplement consistency",
                   "additional RNG stream and accepted-shuffle positions"],
        "east_hcp": dict(sorted(east_hcp.items())), "east_ltc": dict(sorted(east_ltc.items())),
        "east_shapes": dict(east_shapes.most_common()),
        "north_hcp": dict(sorted(north_hcp.items())), "north_spades": dict(sorted(north_spades.items())),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("report")
    parser.add_argument("--source", help="Original v6 deals.json; defaults to sibling run_v6_10000")
    parser.add_argument("--expected-count", type=int, default=10000)
    parser.add_argument("--expected-seed", type=int, default=2026111108)
    args = parser.parse_args()
    report = check(args.dataset, args.source, args.expected_count, args.expected_seed)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
