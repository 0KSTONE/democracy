from dataclasses import dataclass
from typing import Callable, Dict

Score = int  # 0..5

@dataclass
class Agent:
    name: str
    score_fn: Callable[[Dict], Score]
    weight: float = 1.0

def cost_agent():
    def _score(o: Dict) -> Score:
        if o.get("est_cost", 1e9) <= 0.02:
            return 5
        elif o.get("est_cost", 1e9) <= 0.06:
            return 2
        return 0
    return Agent("CostGuard", _score, weight=1.0)

def quality_agent():
    def _score(o: Dict) -> Score:
        return {"fast": 2, "balanced": 4, "best": 5}.get(o.get("mode", "balanced"), 3)
    return Agent("Quality", _score, weight=1.0)

def safety_agent():
    risky = {"scrape_untrusted": 1, "use_tool": 3, "summarize": 5}
    def _score(o: Dict) -> Score:
        return risky.get(o.get("action", "summarize"), 3)
    return Agent("Safety", _score, weight=1.0)