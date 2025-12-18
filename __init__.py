from dataclasses import dataclass
from typing import List, Dict, Callable, Tuple
import random

Score = int  # 0..5

@dataclass
class Ballot:
    # scores[candidate_id] = 0..5
    scores: Dict[str, Score]

def star_tally(ballots: List[Ballot]) -> Tuple[str, Dict[str, int]]:
    # 1) Score round
    totals = {}
    for b in ballots:
        for c, s in b.scores.items():
            totals[c] = totals.get(c, 0) + s
    if len(totals) < 2:
        # If only one candidate, it wins by default
        winner = next(iter(totals)) if totals else None
        return winner, totals

    # 2) Pick top two by total score (break ties deterministically by name)
    top_two = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    a, b = top_two[0][0], top_two[1][0]

    # 3) Runoff: preference count
    a_pref = b_pref = 0
    for ballot in ballots:
        sa, sb = ballot.scores.get(a, 0), ballot.scores.get(b, 0)
        if sa > sb: a_pref += 1
        elif sb > sa: b_pref += 1
        else:
            # exact tie on this ballot: no preference (can also split 0.5/0.5 if you like)
            pass

    if a_pref > b_pref: winner = a
    elif b_pref > a_pref: winner = b
    else:
        # absolute tie: tie-break by higher total, then name
        if totals[a] > totals[b]: winner = a
        elif totals[b] > totals[a]: winner = b
        else: winner = min(a, b)
    return winner, totals

# --- Example "AI council" ---

Candidate = str
Option = Dict[str, str]  # your payload, e.g. {"tool":"bing", "prompt":"..."}

@dataclass
class Agent:
    name: str
    score_fn: Callable[[Option], Score]
    weight: float = 1.0  # allow reputation weighting

def build_ballot(agent: Agent, options: Dict[Candidate, Option]) -> Ballot:
    scores = {}
    for cid, opt in options.items():
        s = agent.score_fn(opt)
        # clamp and weight
        s = max(0, min(5, int(round(s * agent.weight))))
        scores[cid] = s
    return Ballot(scores)

# Example agents with different priorities
def cost_agent(max_cost=0.02) -> Agent:
    return Agent(
        name="CostGuard",
        weight=1.0,
        score_fn=lambda o: 5 if o.get("est_cost", 1e9) <= max_cost else (2 if o.get("est_cost", 1e9) <= max_cost*3 else 0)
    )

def quality_agent() -> Agent:
    return Agent(
        name="Quality",
        score_fn=lambda o: { "fast":2, "balanced":4, "best":5 }.get(o.get("mode","balanced"), 3)
    )

def safety_agent() -> Agent:
    risky = {"scrape_untrusted":1, "use_tool":3, "summarize":5}
    return Agent(
        name="Safety",
        score_fn=lambda o: risky.get(o.get("action","summarize"), 3)
    )

# Wire it up
if __name__ == "__main__":
    options = {
        "A": {"action":"summarize", "mode":"best", "est_cost":0.015},
        "B": {"action":"use_tool", "mode":"balanced", "est_cost":0.030},
        "C": {"action":"scrape_untrusted", "mode":"fast", "est_cost":0.005},
    }
    agents = [cost_agent(), quality_agent(), safety_agent()]
    ballots = [build_ballot(a, options) for a in agents]
    winner, totals = star_tally(ballots)
    print("Totals:", totals)
    print("Winner:", winner, "→", options[winner])
