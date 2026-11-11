"""Full single-suit Kaplan-Rubens contribution for four/five-card holdings.

Richard Pavlicek, https://www.rpbridge.net/8j19.htm, steps 1--23.
Whole-hand adjustments are not allocated to this suit. Step 8 requires
neither the eight nor ten (not merely absence of the pair).
"""
from functools import lru_cache


@lru_cache(maxsize=None)
def knr_suit_points(cards):
    if len(cards) not in (4, 5) or len(cards) != len(set(cards)):
        raise ValueError('Expected four or five distinct ranks')
    h = set(cards)
    if not h <= set('AKQJT98765432'):
        raise ValueError('Invalid card rank')
    # Half-point quality units, then scaled by suit length / 10.
    q2 = sum({'A': 8, 'K': 6, 'Q': 4, 'J': 2, 'T': 1}.get(c, 0) for c in h)
    if 'T' in h and ('J' in h or len(h & set('AKQJ')) >= 2):
        q2 += 1
    if '9' in h and ('8' in h or 'T' in h or len(h & set('AKQJT')) == 2):
        q2 += 1
    if '9' in h and '8' not in h and 'T' not in h and len(h & set('AKQJ')) == 3:
        q2 += 1
    c4 = 12 * ('A' in h) + 8 * ('K' in h)
    if 'Q' in h:
        c4 += 4 if h & set('AK') else 3
    if 'J' in h:
        higher = len(h & set('AKQ'))
        c4 += 2 if higher == 2 else 1 if higher == 1 else 0
    if 'T' in h:
        higher = len(h & set('AKQJ'))
        c4 += int(higher == 2) + int('9' in h and higher == 1)
    return (q2 * len(cards) + 5 * c4) / 20
