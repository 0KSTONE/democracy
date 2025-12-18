# council/demo_task_vote.py
from dataclasses import dataclass
from typing import Dict, Callable, List, Tuple
import argparse
import json
import os
import re

import delivery_vote as finance_vote

Score = int  # 0..5

DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mymodel:latest")
PREFER_GPU = os.getenv("OLLAMA_USE_GPU", "1") != "0"

@dataclass
class Agent:
    name: str
    score_fn: Callable[[Dict], Score]
    weight: float = 1.0

@dataclass
class Ballot:
    scores: Dict[str, Score]

def clamp(x, lo=0, hi=5): return max(lo, min(hi, x))

def build_ballot(agent: Agent, options: Dict[str, Dict]) -> Ballot:
    scores = {}
    for cid, opt in options.items():
        s = agent.score_fn(opt)
        s = clamp(int(round(s * agent.weight)))
        scores[cid] = s
    return Ballot(scores)

def star_tally(ballots: List[Ballot]) -> Tuple[str, Dict[str, int]]:
    totals: Dict[str, int] = {}
    for b in ballots:
        for c, s in b.scores.items():
            totals[c] = totals.get(c, 0) + s
    if not totals:
        return None, {}
    if len(totals) == 1:
        return next(iter(totals)), totals

    # top two by total then name
    top_two = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    a, b = top_two[0][0], top_two[1][0]

    # runoff
    a_pref = b_pref = 0
    for ballot in ballots:
        sa, sb = ballot.scores.get(a, 0), ballot.scores.get(b, 0)
        if sa > sb: a_pref += 1
        elif sb > sa: b_pref += 1
    if a_pref > b_pref: winner = a
    elif b_pref > a_pref: winner = b
    else:
        # tie → higher total, then name
        if totals[a] > totals[b]: winner = a
        elif totals[b] > totals[a]: winner = b
        else: winner = min(a, b)
    return winner, totals

# === Ollama-backed scoring ===

def _load_ollama():
    try:
        import ollama as _ollama  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install the `ollama` Python package and ensure the Ollama daemon is running.") from exc
    return _ollama

def _gpu_options():
    if not PREFER_GPU:
        return {}
    num_gpu_raw = os.getenv("OLLAMA_NUM_GPU")
    try:
        num_gpu = int(num_gpu_raw) if num_gpu_raw else 1
    except ValueError:
        num_gpu = 1
    # If the server ignores this option, we fall back to CPU automatically in _chat_once.
    return {"num_gpu": num_gpu}

def _chat_once(messages: List[Dict[str, str]], model: str):
    ollama = _load_ollama()
    opts = _gpu_options()
    try:
        # Removed timeout argument
        resp = ollama.chat(model=model, messages=messages, options=opts or None)
    except Exception as e:
        print(f"Error during chat: {e}")
        # Retry without GPU options in case the server/model cannot honor them.
        try:
            resp = ollama.chat(model=model, messages=messages, options=None)
        except Exception:
            raise
    return resp["message"]["content"]

def _parse_score(text: str) -> Score:
    m = re.search(r"\b([0-5])\b", text)
    if not m:
        raise ValueError(f"Could not parse score from response: {text!r}")
    return int(m.group(1))

def ollama_task_agent(name: str, persona: str, available_min: int, energy_level: int, model: str = DEFAULT_OLLAMA_MODEL):
    """
    Create an Agent that scores tasks via the local Ollama model.
    """
    def _score(o: Dict) -> Score:
        prompt = (
            f"You are {name}, {persona}. Rate the candidate task for whether it should be done next."
            f"\nAvailable minutes: {available_min}"
            f"\nEnergy level: {energy_level}/5"
            f"\nTask JSON: {json.dumps(o, sort_keys=True)}"
            "\nReturn only a single integer score 0-5 (0 = reject now, 5 = do now)."
        )
        messages = [
            {"role": "system", "content": "You return only a single integer 0-5 with no extra text."},
            {"role": "user", "content": prompt},
        ]
        content = _chat_once(messages, model=model)
        return clamp(_parse_score(content))
    return Agent(name, _score, weight=1.0)

# === Heuristic agents (fallback) ===

def cost_agent():
    # Lower setup friction wins (0..5). Treat >5 min setup as bad.
    def _score(o: Dict) -> Score:
        setup = o.get("setup_min", 0)
        if setup <= 1: return 5
        if setup <= 2: return 4
        if setup <= 3: return 3
        if setup <= 5: return 2
        return 1
    return Agent("CostGuard", _score, weight=1.0)

def quality_agent(available_min: int, energy_level: int):
    """
    Quality heuristics:
      - Fit: estimated_time <= available_min (hard prefer)
      - ROI: 1..5 subjective payoff (learning, money, unblocks something)
      - Momentum: past_win_rate (0..1) → consistency bonus
      - Energy match: task_energy (1..5) should be <= energy_level+1
    """
    def _score(o: Dict) -> Score:
        est = o.get("est_min", 15)
        fit = 1.0 if est <= available_min else max(0.0, 1.0 - (est - available_min)/available_min if available_min else 0.0)
        roi = o.get("roi", 3) / 5.0
        win = o.get("past_win_rate", 0.5)
        t_energy = o.get("task_energy", 3)
        energy_ok = 1.0 if t_energy <= energy_level + 1 else 0.5 if t_energy == energy_level + 2 else 0.0
        raw = 5.0 * (0.40*fit + 0.35*roi + 0.15*win + 0.10*energy_ok)
        return clamp(int(round(raw)))
    return Agent("Quality", _score, weight=1.0)

def safety_agent(available_min: int, energy_level: int):
    """
    Safety heuristics:
      - Block tasks longer than 2× available time.
      - Penalize if task_energy > energy_level+2.
      - Penalize if recent_fail_rate high.
    """
    def _score(o: Dict) -> Score:
        est = o.get("est_min", 15)
        if available_min and est > 2*available_min:
            return 0  # veto: unrealistic for the window
        t_energy = o.get("task_energy", 3)
        if t_energy > energy_level + 2:
            return 1  # too heavy for current state
        fail = o.get("recent_fail_rate", 0.2)  # 0..1
        base = 5 - int(round(5*fail))  # more fails → lower score
        return clamp(base)
    return Agent("Safety", _score, weight=1.0)

# === Decision runners ===

def decide_next_task(options: Dict[str, Dict], available_min: int, energy_level: int, use_ollama: bool = True, model: str = DEFAULT_OLLAMA_MODEL):
    if use_ollama:
        agents = [
            ollama_task_agent("Feasibility", "a cautious planner who blocks tasks that do not fit the time/energy window", available_min, energy_level, model=model),
            ollama_task_agent("Payoff", "optimizes for ROI, learning, and momentum while keeping setup friction low", available_min, energy_level, model=model),
            ollama_task_agent("RiskGuard", "avoids overcommitment and failure-prone tasks given the current state", available_min, energy_level, model=model),
        ]
    else:
        agents = [
            cost_agent(),
            quality_agent(available_min, energy_level),
            safety_agent(available_min, energy_level),
        ]
    ballots = [build_ballot(a, options) for a in agents]
    winner, totals = star_tally(ballots)

    if use_ollama:
        print(f"Ollama model: {model} | GPU preferred: {PREFER_GPU}")
    print(f"Available: {available_min} min | Energy: {energy_level}/5\n")
    for ag, b in zip(agents, ballots):
        print(f"{ag.name} -> {b.scores}")
    print("\nTotals:", totals)
    print("Winner:", winner, "→", options[winner])
    return winner

def run_microtask_demo(available_min: int, energy_level: int, use_ollama: bool, model: str):
    # Fill with things you actually can do today
    options = {
        "A_Journal10":   {"est_min":10, "setup_min":0, "roi":4, "past_win_rate":0.8, "task_energy":1, "recent_fail_rate":0.1},
        "B_InboxSweep":  {"est_min":15, "setup_min":1, "roi":3, "past_win_rate":0.7, "task_energy":2, "recent_fail_rate":0.2},
        "C_ReadDS20":    {"est_min":20, "setup_min":1, "roi":5, "past_win_rate":0.6, "task_energy":3, "recent_fail_rate":0.2},
        "D_CalcPractice":{"est_min":30, "setup_min":2, "roi":4, "past_win_rate":0.5, "task_energy":4, "recent_fail_rate":0.3},
        "E_Stretch15":   {"est_min":15, "setup_min":0, "roi":3, "past_win_rate":0.9, "task_energy":1, "recent_fail_rate":0.05},
    }
    decide_next_task(options, available_min=available_min, energy_level=energy_level, use_ollama=use_ollama, model=model)

def run_financial_demo():
    fin = finance_vote.FinanceSnapshot(
        cash_on_hand=16.0,
        bills_due_next_7d=420.0,
        gas_price_per_gal=3.60,
        mpg=15.0,
        base_rate_per_hr=12.0,
        tip_multiplier=1.3,
        miles_per_hr=12.0,
        energy_level=3,
        hours_available_today=6.0,
    )
    finance_vote.decide_delivery(fin)

def main():
    parser = argparse.ArgumentParser(description="Decision helper: financial vs personal/romantic/microtask.")
    parser.add_argument("--decision", choices=["financial", "microtask", "personal", "romantic"], default="financial", help="Type of decision to run.")
    parser.add_argument("--available-min", type=int, default=25, help="Available minutes (microtask).")
    parser.add_argument("--energy", type=int, default=3, help="Energy level 1..5 (microtask).")
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help="Ollama model for microtask agents.")
    parser.add_argument("--no-ollama", action="store_true", help="Disable Ollama-backed agents for microtask decisions.")
    args = parser.parse_args()

    if args.decision == "financial":
        run_financial_demo()
    elif args.decision == "microtask":
        run_microtask_demo(args.available_min, args.energy, not args.no_ollama, args.model)
    elif args.decision in ("personal", "romantic"):
        raise NotImplementedError(f"{args.decision} decision type not implemented yet.")
    else:
        raise ValueError(f"Unknown decision type: {args.decision}")

if __name__ == "__main__":
    main()
