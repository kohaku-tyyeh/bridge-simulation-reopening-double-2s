"""Approved v7 North 1NT-versus-minor selection predicate; cards only."""


def classify(suits):
    hcp = sum({'A': 4, 'K': 3, 'Q': 2, 'J': 1}.get(c, 0)
              for cards in suits.values() for c in cards)
    spades = suits['S']
    minors = [s for s in 'DC' if len(suits[s]) == 5]
    exempt = ('A' in spades or {'K', 'Q'} <= set(spades)
              or (len(spades) >= 4 and {'Q', 'J'} <= set(spades)))
    flags = {'hcp_6_8': 6 <= hcp <= 8,
             'shape_5422': sorted(map(len, suits.values())) == [2, 2, 4, 5],
             'minor_two_AKQJ': any(len(set(suits[s]) & set('AKQJ')) >= 2 for s in minors)}
    return dict(hcp=hcp, five_minor=''.join(minors), spade_exception=exempt,
                **flags, reject=bool(minors) and not exempt and any(flags.values()))
