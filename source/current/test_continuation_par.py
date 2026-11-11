"""Independent legality, scoring and exhaustive endgame oracle for auction Par.

No DDS code is used here. Auction states use NESW seats 0..3 and CDHSN strains
0..4. A bid is 0..34, pass/double/redouble are P/X/XX. This deliberately simple
oracle is suitable for short high-level endgames, not the 10,000-deal run.
"""

from dataclasses import dataclass
from functools import lru_cache
import random


def oracle_score(level, strain, declarer, tricks, doubled=0,
                 vulns=(False, True)):
    """Independent duplicate score, positive to NS, negative to EW."""
    vulnerable = vulns[declarer % 2]
    required = 6 + level
    if tricks < required:
        down = required - tricks
        if doubled == 0:
            score = -down * (100 if vulnerable else 50)
        else:
            if vulnerable:
                score = -(200 + (down - 1) * 300)
            else:
                score = -sum(100 if n == 1 else 200 if n <= 3 else 300
                             for n in range(1, down + 1))
            if doubled == 2:
                score *= 2
    else:
        basic = 20 * level if strain <= 1 else 30 * level
        if strain == 4:
            basic += 10
        contract = basic * (2 ** doubled)
        score = contract + ((500 if vulnerable else 300)
                            if contract >= 100 else 50)
        score += (0, 50, 100)[doubled]
        if level == 6:
            score += 750 if vulnerable else 500
        if level == 7:
            score += 1500 if vulnerable else 1000
        extra = tricks - required
        if doubled:
            score += extra * (200 if vulnerable else 100) * doubled
        else:
            score += extra * (20 if strain <= 1 else 30)
    return score if declarer % 2 == 0 else -score


@dataclass(frozen=True)
class AuctionState:
    bid: int
    declarer: int
    doubled: int
    passes: int
    next_player: int
    first: tuple[int, ...]


INITIAL = AuctionState(8, 1, 1, 0, 3, (0, 0, 0, 0, 1,
                                       0, 0, 1, 1, 0))


def advance(state, action):
    """Apply one legal action; return None on the third consecutive pass."""
    p = state.next_player
    if action == "P":
        if state.passes == 2:
            return None
        return AuctionState(state.bid, state.declarer, state.doubled,
                            state.passes + 1, (p + 1) % 4, state.first)
    if action == "X":
        if state.doubled != 0 or p % 2 == state.declarer % 2:
            raise ValueError("illegal double")
        return AuctionState(state.bid, state.declarer, 1, 0,
                            (p + 1) % 4, state.first)
    if action == "XX":
        if state.doubled != 1 or p % 2 != state.declarer % 2:
            raise ValueError("illegal redouble")
        return AuctionState(state.bid, state.declarer, 2, 0,
                            (p + 1) % 4, state.first)
    if not isinstance(action, int) or not state.bid < action <= 34:
        raise ValueError("illegal bid")
    first = list(state.first)
    index = (p % 2) * 5 + action % 5
    if first[index] == 0:
        first[index] = 1 if p < 2 else 2
    declarer = (p % 2) + 2 * (first[index] - 1)
    return AuctionState(action, declarer, 0, 0, (p + 1) % 4, tuple(first))


def actions(state):
    yield "P"
    if state.doubled == 0 and state.next_player % 2 != state.declarer % 2:
        yield "X"
    if state.doubled == 1 and state.next_player % 2 == state.declarer % 2:
        yield "XX"
    yield from range(state.bid + 1, 35)


def terminal_score(state, table, vulns=(False, True)):
    return oracle_score(state.bid // 5 + 1, state.bid % 5,
                        state.declarer, table[state.bid % 5][state.declarer],
                        state.doubled, vulns)


def exhaustive_par(table, initial, vulns=(False, True), all_contracts=False):
    @lru_cache(None)
    def visit(state):
        results = []
        for action in actions(state):
            child = advance(state, action)
            value = terminal_score(state, table, vulns) if child is None else visit(child)
            results.append(value)
        return (max if state.next_player % 2 == 0 else min)(results)
    value = visit(initial)
    if all_contracts:
        seen, contracts = set(), set()

        def collect(state):
            if state in seen:
                return
            seen.add(state)
            for action in actions(state):
                child = advance(state, action)
                score = terminal_score(state, table, vulns) if child is None else visit(child)
                if score != value:
                    continue
                if child is None:
                    contracts.add((state.bid // 5 + 1, "CDHSN"[state.bid % 5],
                                   "NESW"[state.declarer], state.doubled))
                else:
                    collect(child)

        collect(initial)
        return value, visit.cache_info().currsize, contracts
    return value, visit.cache_info().currsize


def random_endgames(seed=314159, count=50):
    """Produce legal reachable late states without invoking production code."""
    rng = random.Random(seed)
    for _ in range(count):
        state = INITIAL
        # Force some intervening bids to create varying valid first bidders.
        for bid in sorted(rng.sample(range(9, 29), rng.randint(0, 4))):
            for _ in range(rng.randint(0, 2)):
                state = advance(state, "P")
            state = advance(state, bid)
        state = advance(state, rng.randint(29, 34))
        for _ in range(rng.randint(0, 3)):
            nonterminal = [a for a in actions(state)
                           if not (a == "P" and state.passes == 2)]
            state = advance(state, rng.choice(nonterminal))
        table = [[rng.randint(0, 13) for _ in range(4)] for _ in range(5)]
        yield state, table


def unit_checks():
    # Familiar score anchors cover doubled game bonuses, vulnerability,
    # undertrick schedules, overtricks and slams.
    examples = [
        ((2, 3, 1, 8, 1), -670),
        ((2, 3, 1, 7, 1), 200),
        ((2, 3, 1, 6, 1), 500),
        ((2, 3, 1, 5, 1), 800),
        ((2, 3, 0, 6, 1), -300),
        ((2, 3, 0, 4, 1), -800),
        ((2, 3, 0, 4, 2), -1600),
        ((1, 4, 0, 7, 1), 180),
        ((1, 4, 0, 7, 2), 560),
        ((3, 0, 0, 9, 2), 640),
        ((6, 4, 1, 12, 0), -1440),
        ((7, 4, 0, 13, 0), 1520),
        ((2, 3, 1, 9, 1), -870),
    ]
    for arguments, expected in examples:
        assert oracle_score(*arguments) == expected, (arguments, expected)
    assert INITIAL.next_player == 3
    assert "XX" in list(actions(INITIAL)) and "X" not in list(actions(INITIAL))
    state = INITIAL
    for _ in range(2):
        state = advance(state, "P")
    assert state.next_player == 1  # E has an opportunity after W and N pass.
    assert advance(state, "P") is None
    redoubled = advance(state, "XX")
    assert redoubled.passes == 0 and redoubled.doubled == 2
    assert "X" not in list(actions(redoubled)) and "XX" not in list(actions(redoubled))
    # West cannot become declarer in previously bid hearts/spades.
    assert advance(INITIAL, 12).declarer == 1  # W bids 3H, E remains declarer.
    assert advance(INITIAL, 13).declarer == 1  # W bids 3S, E remains declarer.
    # South cannot replace North as NT declarer.
    state = advance(advance(advance(INITIAL, "P"), 9), "P")
    assert state.next_player == 2
    assert advance(state, 14).declarer == 0
    print("PASS: independent score anchors, auction legality, pass termination, first-bidder history.")


def verify_line(initial, table, result, vulns=(False, True)):
    state = initial
    assert result["actions"], "Missing principal variation"
    for i, raw in enumerate(result["actions"]):
        action = {-1: "P", -2: "X", -3: "XX"}.get(raw, raw)
        assert action in list(actions(state)), (state, action)
        child = advance(state, action)
        if child is None:
            assert i == len(result["actions"]) - 1
            assert terminal_score(state, table, vulns) == result["score_ns"]
            contract = result["contract"]
            assert contract == dict(level=state.bid // 5 + 1,
                                    strain="CDHSN"[state.bid % 5],
                                    declarer="NESW"[state.declarer],
                                    doubled=state.doubled)
        else:
            assert i < len(result["actions"]) - 1, "Line did not terminate"
            state = child


def rotate_case(state, table):
    first = [0] * 10
    for side in range(2):
        for strain in range(5):
            old = state.first[side * 5 + strain]
            if old:
                seat = (side + 2 * (old - 1) + 1) % 4
                first[(seat % 2) * 5 + strain] = 1 if seat < 2 else 2
    rotated = AuctionState(state.bid, (state.declarer + 1) % 4,
                           state.doubled, state.passes,
                           (state.next_player + 1) % 4, tuple(first))
    return rotated, [[row[(i - 1) % 4] for i in range(4)] for row in table]


def production_checks(count=60, all_contracts=False):
    import continuation_par as production

    def solve(state, table, vulnerability):
        kwargs = {"want_all": True} if all_contracts else {}
        return production.solve(table, state=production.AuctionState(
            bid=state.bid, declarer=state.declarer, doubled=state.doubled,
            passes=state.passes, next_player=state.next_player,
            first_decl=(state.first[:5], state.first[5:])),
            vulnerability=vulnerability, **kwargs)

    comparisons = 0
    for level in range(1, 8):
        for strain in range(5):
            for tricks in range(14):
                for doubled in range(3):
                    for vulnerable in (False, True):
                        expected = oracle_score(level, strain, 0, tricks, doubled,
                                                (vulnerable, vulnerable))
                        actual = production.score(level, strain, tricks, doubled, vulnerable)
                        assert actual == expected, (level, strain, tricks, doubled, vulnerable)
                        comparisons += 1
    state_total = 0
    for i, (state, table) in enumerate(random_endgames(count=count)):
        vulnerability = i % 4
        vulns = (bool(vulnerability & 1), bool(vulnerability & 2))
        oracle = exhaustive_par(table, state, vulns, all_contracts)
        expected, states = oracle[:2]
        state_total += states
        result = solve(state, table, vulnerability)
        assert result["score_ns"] == expected, (state, table, result, expected)
        verify_line(state, table, result, vulns)
        if all_contracts:
            actual = {(c["level"], c["strain"], c["declarer"], c["doubled"])
                      for c in result["optimal_contracts"]}
            assert actual == oracle[2], (state, table, actual, oracle[2])
        rotated, rotated_table = rotate_case(state, table)
        rotated_vul = ((vulnerability & 1) << 1) | ((vulnerability & 2) >> 1)
        other = solve(rotated, rotated_table, rotated_vul)
        assert other["score_ns"] == -expected, (state, result, other)
        verify_line(rotated, rotated_table, other, tuple(reversed(vulns)))
    print(f"PASS: production scoring matched {comparisons} independent cases; "
          f"{count} exhaustive endgames ({state_total} states), "
          f"{count} seat/vulnerability rotations, all principal variations legal and correctly scored.")
    return {"scoring_cases": comparisons, "exhaustive_endgames": count,
            "oracle_states": state_total, "rotated_endgames": count,
            "complete_contract_sets_compared": count if all_contracts else 0}


def pilot_checks(cache_path, all_contracts=False):
    import json
    from pathlib import Path
    import continuation_par as production

    rows = [json.loads(line) for line in Path(cache_path).read_text().splitlines()]
    assert len(rows) == 100, "Pilot must contain the promised 100 deals"
    branches = contracts_checked = max_nodes = 0
    for row in rows:
        table = row["dd_table_CDHSN_NESW"]
        kwargs = {"want_all": all_contracts} if all_contracts else {}
        result = production.solve(table, **kwargs)
        verify_line(INITIAL, table, result)
        max_nodes = max(max_nodes, result["nodes"])
        root_values = []
        for action in actions(INITIAL):
            child = advance(INITIAL, action)
            assert child is not None
            state = production.AuctionState(
                bid=child.bid, declarer=child.declarer, doubled=child.doubled,
                passes=child.passes, next_player=child.next_player,
                first_decl=(child.first[:5], child.first[5:]))
            extra = {"want_all": False} if all_contracts else {}
            branch = production.solve(table, state=state, want_pv=False, **extra)
            root_values.append(branch["score_ns"])
            branches += 1
        assert result["score_ns"] == min(root_values), (row["number"], result, root_values)
        if all_contracts:
            terminal_set = result["optimal_contracts"]
            assert terminal_set
            unique = set()
            for contract in terminal_set:
                level, strain, declarer, doubled = (
                    contract["level"], "CDHSN".index(contract["strain"]),
                    "NESW".index(contract["declarer"]), contract["doubled"])
                assert oracle_score(level, strain, declarer,
                                    table[strain][declarer], doubled) == result["score_ns"]
                bid = 5 * (level - 1) + strain
                assert bid >= 8
                if bid == 8:
                    assert declarer == 1 and doubled in (1, 2)
                if declarer % 2 == 1 and strain in (2, 3):
                    assert declarer == 1
                if declarer % 2 == 0 and strain == 4:
                    assert declarer == 0
                unique.add((level, strain, declarer, doubled))
                contracts_checked += 1
            assert len(unique) == len(terminal_set)
            c = result["contract"]
            assert (c["level"], "CDHSN".index(c["strain"]),
                    "NESW".index(c["declarer"]), c["doubled"]) in unique
    print(f"PASS:100 pilot root states, {branches} unrestricted West root choices, "
          f"100 legal scored PVs, {contracts_checked} optimal terminal contracts.")
    return {"pilot_deals": len(rows), "root_children": branches,
            "principal_variations": len(rows), "optimal_terminals_checked": contracts_checked,
            "maximum_solver_nodes": max_nodes}


def dds_checks(cache_path):
    import json
    from pathlib import Path
    from dds_backend import DDS
    rows = [json.loads(line) for line in Path(cache_path).read_text().splitlines()]
    engine = DDS(threads=1)
    for row in rows[:3]:
        assert engine.table(row["pbn"]) == row["dd_table_CDHSN_NESW"]
    base = rows[0]
    hands = base["pbn"][2:].split()
    rotated = "N:" + " ".join([hands[-1]] + hands[:-1])
    expected = [[r[(i - 1) % 4] for i in range(4)]
                for r in base["dd_table_CDHSN_NESW"]]
    assert engine.table(rotated) == expected
    swapped = []
    for hand in hands:
        s, h, d, c = hand.split(".")
        swapped.append(".".join((s, h, c, d)))
    expected = [base["dd_table_CDHSN_NESW"][i] for i in [1, 0, 2, 3, 4]]
    assert engine.table("N:" + " ".join(swapped)) == expected
    print("PASS:3 single-vs-batch DDS tables, one seat rotation and one suit permutation.")
    return {"single_vs_batch": 3, "seat_rotations": 1, "suit_permutations": 1}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--all-contracts", action="store_true")
    parser.add_argument("--pilot-cache")
    parser.add_argument("--dds", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    report = {"status": "passed"}
    unit_checks()
    if args.production:
        report["independent_oracle"] = production_checks(args.count, args.all_contracts)
    else:
        sizes = [exhaustive_par(table, state)[1] for state, table in random_endgames(count=12)]
        print(f"Independent endgame oracle exercised on 12 cases; max cached states {max(sizes)}.")
    if args.pilot_cache:
        report["pilot"] = pilot_checks(args.pilot_cache, args.all_contracts)
        if args.dds:
            report["dds"] = dds_checks(args.pilot_cache)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
