from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Tuple


@dataclass
class Bill:
    amount: float
    due_date: str  # ISO format: yyyy-mm-dd


# ---- User-editable inputs (change values here only) ----
# Bills and finance inputs are defined once here so you don't have to hunt for them.
USER_BILLS: List[Bill] = [
    Bill(amount=280, due_date="2025-12-23"),
    Bill(amount=155, due_date="2025-12-26"),
]

USER_INPUTS: Dict[str, object] = {
    "cash_on_hand": 120.0,
    "gas_price_per_gal": 3.0,
    "mpg": 15.0,
    "base_rate_per_hr": 12.0,
    "tip_multiplier": 1.3,
    "miles_per_hr": 12.0,
    "energy_level": 3,
    "hours_available_today": 6.0,
    "wants_cost": 165.0,
    "bill_window_days": 7,
    # Promotions: toggle and set expected payout for today and the next two days.
    "promo_available_today": True,
    "promo_expected_today": 21.0,          # expected max promo payout today
    "promo_expected_next_days": (21.0, 54.5),  # tuple/list of up to 2 days of promo potential
}


@dataclass
class FinanceSnapshot:
    cash_on_hand: float              # e.g., 64.00
    bills_due_next_7d: float         # total due within the next 7 days (auto-computed)
    bill_shortfall: float            # max(0, bills_due_next_7d - cash_on_hand)
    bill_daily_need: float           # dollars needed per day to cover shortfall by next due date
    next_bill_due_in_days: int       # days until the next due bill (>= 0)
    gas_price_per_gal: float         # e.g., 3.60
    mpg: float                       # your car's miles per gallon
    base_rate_per_hr: float          # conservative $/hr estimate (base pay only)
    tip_multiplier: float            # 1.0 = no tips; 1.3 = +30%
    miles_per_hr: float              # avg miles driven per working hour
    energy_level: int                # 1..5 honest energy
    hours_available_today: float     # max hours you can work today
    wants_cost: float           # Optional cost for wants (e.g., leisure)
    promo_available_today: bool 
    promo_expected_today: float 
    promo_expected_next_days: Tuple[float, ...] = ()


def calculate_bills_due(bills: List[Bill], days: int = 7) -> float:
    """Return total amount of bills due within the next `days` days."""
    today = date.today()
    return sum(
        bill.amount
        for bill in bills
        if 0 <= (date.fromisoformat(bill.due_date) - today).days <= days
    )


def summarize_bill_pressure(
    bills: List[Bill],
    cash_on_hand: float,
    window_days: int = 7,
) -> Dict[str, float]:
    """
    Summaries the near-term bill pressure.

    Returns a dict with:
    - total_due: total amount due within `window_days`
    - shortfall: amount not covered by current cash
    - next_due_in_days: days until the closest due bill (>= 0, large if none)
    - daily_need: dollars per day needed to close the shortfall before the closest due date
    """
    today = date.today()
    upcoming = []
    for bill in bills:
        due = date.fromisoformat(bill.due_date)
        if due >= today:
            upcoming.append((due, bill.amount))
    if not upcoming:
        return {
            "total_due": 0.0,
            "shortfall": 0.0,
            "next_due_in_days": 365,  # effectively no pressure
            "daily_need": 0.0,
        }

    total_due = sum(amount for due, amount in upcoming if (due - today).days <= window_days)
    next_due_days = min((due - today).days for due, _ in upcoming)
    shortfall = max(0.0, total_due - cash_on_hand)
    days_until_due = max(1, next_due_days)  # avoid division by zero
    daily_need = shortfall / days_until_due

    return {
        "total_due": round(total_due, 2),
        "shortfall": round(shortfall, 2),
        "next_due_in_days": next_due_days,
        "daily_need": round(daily_need, 2),
    }


def build_finance_snapshot(
    bills: List[Bill],
    cash_on_hand: float,
    gas_price_per_gal: float,
    mpg: float,
    base_rate_per_hr: float,
    tip_multiplier: float,
    miles_per_hr: float,
    energy_level: int,
    hours_available_today: float,
    wants_cost: float,
    bill_window_days: int = 7,
    promo_available_today: bool = False,
    promo_expected_today: float = 0.0,
    promo_expected_next_days: Tuple[float, ...] = (),
) -> FinanceSnapshot:
    """
    Build a FinanceSnapshot where bill-related values are auto-computed.
    Update values here (bill tracker) instead of in delivery_vote.
    """
    bill_stats = summarize_bill_pressure(bills, cash_on_hand, bill_window_days)
    return FinanceSnapshot(
        cash_on_hand=cash_on_hand,
        bills_due_next_7d=bill_stats["total_due"],
        bill_shortfall=bill_stats["shortfall"],
        bill_daily_need=bill_stats["daily_need"],
        next_bill_due_in_days=bill_stats["next_due_in_days"],
        gas_price_per_gal=gas_price_per_gal,
        mpg=mpg,
        base_rate_per_hr=base_rate_per_hr,
        tip_multiplier=tip_multiplier,
        miles_per_hr=miles_per_hr,
        energy_level=energy_level,
        hours_available_today=hours_available_today,
        wants_cost=wants_cost,
        promo_available_today=promo_available_today,
        promo_expected_today=promo_expected_today,
        promo_expected_next_days=promo_expected_next_days,
    )


def build_snapshot_from_config(
    bills: List[Bill] = USER_BILLS,
    inputs: Dict[str, object] = USER_INPUTS,
) -> FinanceSnapshot:
    """
    Convenience wrapper that builds a FinanceSnapshot using the single config block above.
    """
    promo_next = inputs.get("promo_expected_next_days", ())
    if isinstance(promo_next, list):
        promo_next = tuple(promo_next)
    return build_finance_snapshot(
        bills=bills,
        cash_on_hand=float(inputs["cash_on_hand"]),
        gas_price_per_gal=float(inputs["gas_price_per_gal"]),
        mpg=float(inputs["mpg"]),
        base_rate_per_hr=float(inputs["base_rate_per_hr"]),
        tip_multiplier=float(inputs["tip_multiplier"]),
        miles_per_hr=float(inputs["miles_per_hr"]),
        energy_level=int(inputs["energy_level"]),
        hours_available_today=float(inputs["hours_available_today"]),
        wants_cost=float(inputs.get("wants_cost", 0.0)),
        bill_window_days=int(inputs.get("bill_window_days", 7)),
        promo_available_today=bool(inputs.get("promo_available_today", False)),
        promo_expected_today=float(inputs.get("promo_expected_today", 0.0)),
        promo_expected_next_days=tuple(promo_next),
    )


# Example usage
if __name__ == "__main__":
    snapshot = build_snapshot_from_config()
    print("FinanceSnapshot:", snapshot)
