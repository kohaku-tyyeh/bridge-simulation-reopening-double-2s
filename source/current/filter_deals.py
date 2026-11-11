#!/usr/bin/env python3
"""Generate review deals for P-(1S)-X-(P), 1NT-(2H)-P-(2S), P-(P)-?.

North = partner/dealer; East = opener; South = us; West = responder.
Uniformly shuffle the 39 unknown cards, then reject against explicit rules.
These are review samples under a provisional bidding model, not a strength
comparison between Pass and Double and not an empirical bidding distribution.
Python standard library only. All thresholds are editable in rules.json.
"""

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import random
import time
from urllib.parse import urlencode

from knr_suit import knr_suit_points
from nt_choice import classify as nt_choice

SUITS = "SHDC"
RANKS = "AKQJT98765432"
POINTS = {"A": 4, "K": 3, "Q": 2, "J": 1}
AUCTION = ["P", "1S", "D", "P", "1N", "2H", "P", "2S", "P", "P"]
FIXED_SOUTH = ("3", "9754", "AKT8", "A764")


@dataclass(frozen=True)
class Hand:
    suits: tuple[str, ...]

    @classmethod
    def from_cards(cls, cards):
        sorted_cards = sorted(cards)
        return cls(tuple("".join(RANKS[c % 13] for c in sorted_cards
                                 if c // 13 == s) for s in range(4)))

    @property
    def cards(self):
        return [13 * s + RANKS.index(r)
                for s, ranks in enumerate(self.suits) for r in ranks]

    @property
    def shape(self):
        return tuple(map(len, self.suits))

    @property
    def hcp(self):
        return sum(POINTS.get(r, 0) for ranks in self.suits for r in ranks)

    @property
    def balanced(self):
        return sorted(self.shape, reverse=True) in (
            [4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2])

    @property
    def losing_tricks(self):
        """Basic LTC: singleton A, doubleton AK, 3+ AKQ; no adjustments."""
        return sum(sum(honor not in ranks for honor in "AKQ"[:len(ranks)])
                   for ranks in self.suits)

    @property
    def viewer(self):
        return "".join(s + ranks for s, ranks in zip(SUITS, self.suits)).lower()


def stopper(ranks):
    """Provisional natural-NT stopper: A, Kx, Qxx, or Jxxx (or longer)."""
    return any(rank in ranks and len(ranks) >= length
               for rank, length in (("A", 1), ("K", 2), ("Q", 3), ("J", 4)))


def trump_promotion_floor(spades):
    """Conservative suit-quality proxy, using only this player's cards.

    For each top-rank prefix, count our cards minus missing cards. Missing
    high trumps can each beat at most one of our high trumps; take the best
    surplus. This is NOT a guarantee of tricks in full-hand play (entries,
    ruffs, discards, and incomplete trump play can matter).
    """
    balance = best = 0
    for rank in RANKS:
        balance += 1 if rank in spades else -1
        best = max(best, balance)
    return best


def four_spade_penalty(spades, total_hcp, side_suits, rules):
    return (len(spades) == 4
            and total_hcp >= rules['penalty_min_hcp']
            and knr_suit_points(spades) >= rules['penalty_four_min_knr']
            and any(honor in ranks for ranks in side_suits
                    for honor in rules['penalty_four_spades_side_honors']))


def penalty_reason(hand, rules):
    spades = hand.suits[0]
    if len(spades) == 4:
        if four_spade_penalty(spades, hand.hcp, hand.suits[1:], rules):
            return 'four_knr_with_side_high_honor'
    elif len(spades) == 5:
        if rules['penalty_five_inherits_four']:
            for i, rank in enumerate(spades):
                if four_spade_penalty(spades[:i] + spades[i+1:],
                                      hand.hcp - POINTS.get(rank, 0),
                                      hand.suits[1:], rules):
                    return 'five_inherits_qualifying_four'
        controls = 'A' in spades or {'K', 'Q'} <= set(spades)
        minimum = (rules['penalty_five_control_min_hcp'] if controls
                   else rules['penalty_min_hcp'])
        if (hand.hcp >= minimum
                and knr_suit_points(spades) >= rules['penalty_five_min_knr']):
            return ('five_knr_seven_hcp_with_control' if hand.hcp < rules['penalty_min_hcp']
                    else 'five_knr_eight_hcp')
    return None


def penalty_ready(hand, rules):
    return penalty_reason(hand, rules) is not None


def weak_four_card_hearts(hearts):
    """Provisional diagnostic, not by itself a reason to reject a 2H rebid."""
    return (len(hearts) == 4 and not set(hearts).intersection("AK")
            and len(set(hearts).intersection("QJT")) <= 1)


def east_failures(hand, rules):
    s, h, _, _ = hand.shape
    failures = []
    if not rules["opener_min_hcp"] <= hand.hcp <= rules["opener_max_hcp"]:
        failures.append("E_hcp")
    if s < 5 or h < 4:
        failures.append("E_major_lengths")
    if h > s:
        failures.append("E_open_longer_major")
    if [s, h] in rules.get("opener_excluded_major_lengths_for_2H", []):
        failures.append("E_would_not_compete_2H_with_this_major_shape")
    if "opener_2H_hcp_by_major_lengths" in rules:
        bounds = rules["opener_2H_hcp_by_major_lengths"].get(f"{s}-{h}")
        if bounds is None and s >= 6 and h >= 5:
            bounds = rules.get("opener_2H_longer_two_suiter_hcp")
        if bounds is None:
            failures.append("E_2H_major_shape_not_modelled")
        elif not bounds[0] <= hand.hcp <= bounds[1]:
            failures.append("E_2H_shape_hcp_band")
    elif (hand.hcp <= rules["weak_opener_max_hcp"]
            and s + h < rules["weak_opener_min_major_cards"]):
        # Compatibility with archived v1-v3 rule files.
        failures.append("E_weak_requires_extra_shape")
    if hand.losing_tricks < rules["opener_min_losing_tricks"]:
        failures.append("E_too_few_losers_to_pass_2S")
    quality = rules.get("opener_2H_weak_hearts_policy")
    if (quality and quality.get("mode", "review_only") == "exclude"
            and hand.hcp < quality["extra_values_hcp"]
            and s == quality["alternative_spade_length"]
            and weak_four_card_hearts(hand.suits[1])
            and len(set(hand.suits[0]).intersection("AKQJT"))
            >= quality["alternative_spade_top5_min"]):
        failures.append("E_low_range_64_prefers_2S_with_weak_hearts")
    return failures


def north_failures(hand, rules):
    failures = []
    if not rules["partner_nt_min_hcp"] <= hand.hcp <= rules["partner_nt_max_hcp"]:
        failures.append("N_1NT_hcp")
    if not stopper(hand.suits[0]):
        failures.append("N_1NT_spade_stopper")
    if hand.shape[1] > rules["partner_max_hearts"]:
        failures.append("N_would_prefer_hearts")
    if min(hand.shape) < rules["partner_min_suit_length"]:
        failures.append("N_1NT_shortness")
    if max(hand.shape) > rules["partner_max_suit_length"]:
        failures.append("N_1NT_long_suit")
    if penalty_ready(hand, rules):
        failures.append("N_would_penalty_double_2S")
    if rules.get('partner_nt_minor_choice_filter', False) and nt_choice(dict(zip(SUITS, hand.suits)))['reject']:
        failures.append('N_prefers_minor_response_to_1NT')
    return failures


def west_failures(hand, rules):
    s, h, _, _ = hand.shape
    failures = []
    if s > rules["responder_max_spades"]:
        failures.append("W_5plus_spades_not_modelled")
    if s <= 2:
        maximum = rules["responder_0_2_spades_max_hcp"]
    elif s == 3 and hand.balanced:
        maximum = rules["responder_balanced_3_spades_max_hcp"]
    else:
        maximum = rules["responder_other_support_max_hcp"]
    if hand.hcp > maximum:
        failures.append("W_initial_pass_hcp")
    if hand.hcp > rules.get("responder_2S_max_hcp", 40):
        failures.append("W_2S_hcp")
    # Explicit baseline restriction, NOT a logical equivalence in real bidding:
    # only S >= H preference cases are sampled in this first review batch.
    if rules["preference_requires_spades_ge_hearts"] and s < h:
        failures.append("W_2S_preference")
    return failures


def deal_failures(deal, rules):
    failures = []
    if deal["S"].suits != FIXED_SOUTH:
        failures.append("fixed_S")
    cards = [c for seat in "NESW" for c in deal[seat].cards]
    if any(len(deal[seat].cards) != 13 for seat in "NESW"):
        failures.append("13_cards_each")
    if len(cards) != 52 or set(cards) != set(range(52)):
        failures.append("complete_unique_deck")
    if sum(deal[seat].hcp for seat in "NESW") != 40:
        failures.append("40_total_hcp")
    failures += east_failures(deal["E"], rules)
    failures += north_failures(deal["N"], rules)
    failures += west_failures(deal["W"], rules)
    return failures


def viewer_link(deal):
    params = {seat.lower(): deal[seat].viewer for seat in "NESW"}
    # Do not set `i`: BBO treats it as an intro and initially hides the auction.
    params.update(d="n", v="e", a="".join(AUCTION).lower(), pc="n",
                  sn="You", nn="Partner", en="Opener", wn="Responder")
    return "https://www.bridgebase.com/tools/handviewer.html?" + urlencode(params)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261110)
    parser.add_argument("--max-attempts", type=int, default=2000000)
    parser.add_argument("--rules", type=Path,
                        default=Path(__file__).with_name("rules.json"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).parent)
    parser.add_argument('--progress-every', type=int, default=1000000)
    args = parser.parse_args()
    if args.count < 1 or args.max_attempts < 1:
        parser.error("count and max-attempts must be positive")
    rules = json.loads(args.rules.read_text())
    south = Hand(FIXED_SOUTH)
    fixed_cards = set(south.cards)
    unknown = [c for c in range(52) if c not in fixed_cards]
    rng = random.Random(args.seed)
    accepted, seen, rejections = [], set(), Counter()
    started = time.monotonic()
    for attempt in range(1, args.max_attempts + 1):
        if args.progress_every and attempt % args.progress_every == 0:
            print(f'Shuffles {attempt:,}; accepted {len(accepted):,}; '
                  f'{time.monotonic()-started:.1f}s', flush=True)
        rng.shuffle(unknown)
        east = Hand.from_cards(unknown[:13])
        failures = east_failures(east, rules)
        if failures:
            rejections[failures[0]] += 1
            continue
        north = Hand.from_cards(unknown[13:26])
        failures = north_failures(north, rules)
        if failures:
            rejections[failures[0]] += 1
            continue
        west = Hand.from_cards(unknown[26:])
        failures = west_failures(west, rules)
        if failures:
            rejections[failures[0]] += 1
            continue
        deal = dict(N=north, E=east, S=south, W=west)
        identity = tuple(deal[s].viewer for s in "NESW")
        if identity in seen:
            rejections["duplicate"] += 1
            continue
        assert not deal_failures(deal, rules)
        seen.add(identity)
        accepted.append({
            "number": len(accepted) + 1,
            "hands": {s: {"suits": dict(zip(SUITS, deal[s].suits)),
                          "hcp": deal[s].hcp, "shape_SHDC": deal[s].shape,
                          "balanced": deal[s].balanced,
                          "basic_ltc": deal[s].losing_tricks}
                      for s in "NESW"},
            "north_penalty_check": {
                "spade_promotion_floor": trump_promotion_floor(north.suits[0]),
                "spade_knr_points": (knr_suit_points(north.suits[0])
                                     if len(north.suits[0]) in (4, 5) else None),
                "best_four_spade_knr_points": (
                    max(knr_suit_points(north.suits[0][:i]+north.suits[0][i+1:])
                        for i in range(5)) if len(north.suits[0]) == 5 else None),
                "penalty_reason": penalty_reason(north, rules),
            },
            "handviewer_url": viewer_link(deal),
        })
        if len(accepted) == args.count:
            break
    if len(accepted) != args.count:
        raise SystemExit(f"Only {len(accepted)} accepted in {attempt} attempts")
    payload = {
        "seed": args.seed, "attempts": attempt, "rules": rules,
        "generation_seconds": time.monotonic() - started,
        "dealer": "N", "vulnerability": "EW", "next_to_act": "S",
        "auction": AUCTION, "rejection_first_reason_counts": dict(rejections),
        "deals": accepted,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "deals.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    # This is generated link data, not a prose document.
    (args.output_dir / "handviewer_links.txt").write_text("\n".join(
        f'{d["number"]}. {d["handviewer_url"]}' for d in accepted) + "\n")
    print(f"Accepted {len(accepted)} unique deals in {attempt} shuffles; seed={args.seed}.")
    for d in accepted:
        print(f'{d["number"]}: ' + "; ".join(
            f'{s} {d["hands"][s]["hcp"]} HCP '
            + "-".join(map(str, d["hands"][s]["shape_SHDC"]))
            + f' LTC={d["hands"][s]["basic_ltc"]}' for s in "NEW"))


if __name__ == "__main__":
    main()
