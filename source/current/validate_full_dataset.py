"""Independent checks of the complete generated review/experiment dataset."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

RANKS = "AKQJT98765432"
SUITS = "SHDC"
SEATS = "NESW"
DECK = {s + r for s in SUITS for r in RANKS}


def check(path, pilot_path):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    pilot = json.loads(Path(pilot_path).read_text())
    assert len(data["deals"]) == 10000
    assert len(pilot["deals"]) == 100
    assert data["seed"] == pilot["seed"] == 20261110
    assert data["rules"] == pilot["rules"]
    assert data["deals"][:100] == pilot["deals"]
    assert data["dealer"] == "N" and data["vulnerability"] == "EW"
    assert data["next_to_act"] == "S"
    assert data["auction"] == ["P", "1S", "D", "P", "1N", "2H", "P", "2S", "P", "P"]
    assert sum(data["rejection_first_reason_counts"].values()) + 10000 == data["attempts"]
    seen = set()
    east_hcp, east_ltc, east_shapes, north_hcp, north_spades = (Counter() for _ in range(5))
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
        assert 11 <= hp["E"] <= 17 and es >= 5 and eh >= 4 and es >= eh
        assert hp["E"] >= 15 or es + eh >= 10
        assert ltc["E"] >= 5

        ns, nh, _, _ = shapes["N"]
        spades = hands["N"]["suits"]["S"]
        assert 6 <= hp["N"] <= 10 and nh <= 3
        assert min(shapes["N"]) >= 2 and max(shapes["N"]) <= 5
        assert ("A" in spades or ("K" in spades and ns >= 2)
                or ("Q" in spades and ns >= 3) or ("J" in spades and ns >= 4))
        floor = max([0] + [2 * sum(r in spades for r in RANKS[:k]) - k for k in range(1, 14)])
        normal_penalty = ns >= 5 and floor >= 2
        four_penalty = ns == 4 and any(all(r in spades for r in core)
                                      for core in ("KQT", "KQJ", "AQT", "AQJ", "AK"))
        four_penalty = four_penalty and any(r in hands["N"]["suits"][s]
                                            for s in "HDC" for r in "AK")
        assert not (hp["N"] >= 8 and (normal_penalty or four_penalty))
        assert record["north_penalty_check"] == {"spade_promotion_floor": floor, "penalty_reason": None}

        ws, wh, _, _ = shapes["W"]
        assert ws <= 4 and ws >= wh
        max_hcp = 9 if ws <= 2 else 5 if ws == 3 and hands["W"]["balanced"] else 4
        assert hp["W"] <= max_hcp

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

    return {
        "status": "passed", "deals_checked": 10000, "unique_deals": len(seen),
        "sha256": hashlib.sha256(raw).hexdigest(), "seed": data["seed"],
        "attempts": data["attempts"], "exact_pilot_prefix": 100,
        "checks": ["52 unique legal cards", "fixed South", "40 total HCP", "29 unknown HCP",
                   "all bidding-model rules independently evaluated", "recorded metadata recomputed",
                   "all Handviewer cards/auction/vulnerability", "generation accounting"],
        "east_hcp": dict(sorted(east_hcp.items())), "east_ltc": dict(sorted(east_ltc.items())),
        "east_shapes": dict(east_shapes.most_common()),
        "north_hcp": dict(sorted(north_hcp.items())), "north_spades": dict(sorted(north_spades.items())),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("pilot")
    parser.add_argument("report")
    args = parser.parse_args()
    report = check(args.dataset, args.pilot)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
