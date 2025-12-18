from core.vote_core import star_tally, Ballot
from core.agent_definitions import Agent
from typing import Dict

def sleep_agent():
    def _score(o: Dict) -> int:
        if o.get("hours") < 7:
            return 0  # Less than 7 hours is bad
        elif 7 <= o.get("hours") <= 9:
            return 5  # Ideal sleep range
        return 2  # More than 9 hours is suboptimal
    return Agent("Sleep", _score)

def meditation_agent():
    def _score(o: Dict) -> int:
        if o.get("time") in ["morning", "evening"]:
            return 5  # Evidence favors morning/evening meditation
        return 1
    return Agent("Meditation", _score)

def decide_health(options: Dict[str, Dict]):
    agents = [sleep_agent(), meditation_agent()]
    ballots = [Ballot({cid: agent.score_fn(opt) for cid, opt in options.items()}) for agent in agents]
    winner, totals = star_tally(ballots)
    return winner, totals