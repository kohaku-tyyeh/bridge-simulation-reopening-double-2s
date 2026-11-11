"""共用：牌、輸入列、計分（Python 版，與 C++ 互相對照）、IMP。"""
SEATS = 'NESW'; RANKS = 'AKQJT98765432'
FIXED_SOUTH = '3.9754.AKT8.A764'
BIDSTR = 'CDHSN'

def parse_pbn(pbn):
    first, rest = pbn.split(':')
    hands = rest.split()
    i0 = SEATS.index(first)
    out = {}
    for k, h in enumerate(hands):
        out[SEATS[(i0 + k) % 4]] = h.split('.')  # S H D C
    return out

def check_deal(h):
    cards = [(s, r) for seat in SEATS for s, ranks in zip('SHDC', h[seat]) for r in ranks]
    assert all(sum(map(len, h[x])) == 13 for x in SEATS), 'hand size'
    assert len(cards) == 52 and len(set(cards)) == 52, 'deck not complete/unique'
    assert '.'.join(h['S']) == FIXED_SOUTH, 'South changed'

def protect_info(h):
    """依 C D H S：南北合計張數、東西較長一家的張數。"""
    idx = {'S': 0, 'H': 1, 'D': 2, 'C': 3}
    ns = [len(h['N'][idx[s]]) + len(h['S'][idx[s]]) for s in 'CDHS']
    ew = [max(len(h['E'][idx[s]]), len(h['W'][idx[s]])) for s in 'CDHS']
    return ns, ew

# 起始狀態：2♠（bid index 8）東家作莊、已被南家賭倍、0 Pass、輪西家；
# first[side*5+strain]：NS 的 NT=北(0)；EW 的 S、H = 東(1)
START = [8, 1, 1, 0, 3] + [-1, -1, -1, -1, 0] + [-1, -1, 1, 1, -1]
PROT = {'a': 0, 'b': 1 << 3, 'c': (1 << 3) | (1 << 4)}

def input_line(bid_id, dd, h, prot):
    """dd: dict[(strain SHDCN, seat)] -> tricks。"""
    t = [dd[(s, x)] for s in 'CDHSN' for x in SEATS]
    ns, ew = protect_info(h)
    return ' '.join(map(str, [bid_id] + t + ns + ew + [PROT[prot]] + START))

def score_decl(level, strain, dbl, tricks, vul):
    need = level + 6
    if tricks >= need:
        per = 20 if strain in 'CD' else 30
        ts = (40 + 30 * (level - 1)) if strain == 'N' else per * level
        ts *= (1, 2, 4)[dbl]
        s = ts + ((500 if vul else 300) if ts >= 100 else 50)
        if level == 6: s += 750 if vul else 500
        if level == 7: s += 1500 if vul else 1000
        over = tricks - need
        s += over * (30 if strain == 'N' else per) if dbl == 0 else over * (200 if vul else 100) * dbl
        s += (0, 50, 100)[dbl]
        return s
    d = need - tricks
    if dbl == 0: return -d * (100 if vul else 50)
    if vul: s = 200 + 300 * (d - 1)
    else: s = 100 if d == 1 else (100 + 200 * (d - 1) if d <= 3 else 500 + 300 * (d - 3))
    return -s * dbl

def score_ns(contract, decl, dd):
    """contract 例 '3CX'；decl 座位；回傳南北分數。"""
    level = int(contract[0]); strain = contract[1]; dbl = contract[2:].count('X')
    side_ns = decl in 'NS'
    s = score_decl(level, strain, dbl, dd[(strain, decl)], vul=not side_ns)
    return s if side_ns else -s

IMP = [20, 50, 90, 130, 170, 220, 270, 320, 370, 430, 500, 600, 750, 900, 1100,
       1300, 1500, 1750, 2000, 2250, 2500, 3000, 3500, 4000]
def imp(diff):
    a = abs(diff); k = sum(1 for x in IMP if a >= x)
    return k if diff >= 0 else -k
