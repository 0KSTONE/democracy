from typing import List, Dict, Tuple
from dataclasses import dataclass

Score = int  # 0..5

@dataclass
class Ballot:
    scores: Dict[str, Score]

def clamp(x, lo=0, hi=5):
    return max(lo, min(hi, x))

def star_tally(ballots: List[Ballot]) -> Tuple[str, Dict[str, int]]:
    totals: Dict[str, int] = {}
    for b in ballots:
        for c, s in b.scores.items():
            totals[c] = totals.get(c, 0) + s
    if not totals:
        return None, {}
    if len(totals) == 1:
        return next(iter(totals)), totals

    # Top two by total score, then name
    top_two = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    a, b = top_two[0][0], top_two[1][0]

    # Runoff
    a_pref = b_pref = 0
    for ballot in ballots:
        sa, sb = ballot.scores.get(a, 0), ballot.scores.get(b, 0)
        if sa > sb:
            a_pref += 1
        elif sb > sa:
            b_pref += 1

    if a_pref > b_pref:
        return a, totals
    elif b_pref > a_pref:
        return b, totals
    else:
        # Tie-break by higher total, then name
        if totals[a] > totals[b]:
            return a, totals
        elif totals[b] > totals[a]:
            return b, totals
        else:
            return min(a, b), totals