"""Account tier and model capability helpers."""

from typing import Optional


PAYGATE_TIER_NOT_PAID = "PAYGATE_TIER_NOT_PAID"
PAYGATE_TIER_ONE = "PAYGATE_TIER_ONE"
PAYGATE_TIER_TWO = "PAYGATE_TIER_TWO"

# A balance that falls to a tenth or less of a balance of at least this many credits within one
# reading is a plan change or a reset, not spending: no request costs thousands of credits.
BALANCE_COLLAPSE_MIN_BEFORE = 2000
BALANCE_COLLAPSE_RATIO = 0.1


def is_balance_collapse(before, after) -> bool:
    """True when the balance dropped so far at once that the account's plan most likely changed."""
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (before, after)):
        return False
    return before >= BALANCE_COLLAPSE_MIN_BEFORE and 0 <= after <= before * BALANCE_COLLAPSE_RATIO


# Text of Flow's plan chip (flow-user-tier-chip) in the languages Flow shows it in, checked as substrings.
_CHIP_FREE = ("FREE", "MIỄN PHÍ", "MIEN PHI", "免费", "免費", "GRATIS", "GRATUIT")
_CHIP_PAID = ("PLUS", "PRO")
_CHIP_ULTRA = ("ULTRA",)


def tier_from_chip_text(text: Optional[str]) -> Optional[str]:
    """The paygate tier that Flow's plan chip names, or None when the text is empty or not recognised."""
    value = " ".join(str(text or "").upper().split())
    if not value:
        return None
    # Order matters: "Google AI Ultra" and "AI Pro" must not be read as free by a stray substring.
    for words, tier in ((_CHIP_ULTRA, PAYGATE_TIER_TWO), (_CHIP_PAID, PAYGATE_TIER_ONE), (_CHIP_FREE, PAYGATE_TIER_NOT_PAID)):
        if any(word in value for word in words):
            return tier
    return None


def normalize_user_paygate_tier(user_paygate_tier: Optional[str]) -> str:
    """Normalize an account tier, defaulting unknown values to free tier."""
    normalized = (user_paygate_tier or "").strip()
    if normalized in {PAYGATE_TIER_NOT_PAID, PAYGATE_TIER_ONE, PAYGATE_TIER_TWO}:
        return normalized
    return PAYGATE_TIER_NOT_PAID


def get_paygate_tier_rank(user_paygate_tier: Optional[str]) -> int:
    """Map account tier to a comparable rank."""
    normalized = normalize_user_paygate_tier(user_paygate_tier)
    if normalized == PAYGATE_TIER_TWO:
        return 2
    if normalized == PAYGATE_TIER_ONE:
        return 1
    return 0


def get_paygate_tier_label(user_paygate_tier: Optional[str]) -> str:
    """Return a readable account tier label."""
    normalized = normalize_user_paygate_tier(user_paygate_tier)
    if normalized == PAYGATE_TIER_TWO:
        return "Ult"
    if normalized == PAYGATE_TIER_ONE:
        return "Pro"
    return "Free"


def get_required_paygate_tier_for_model(model_name: Optional[str]) -> str:
    """Infer the minimum required account tier from a model name."""
    normalized = (model_name or "").strip().lower()
    if not normalized:
        return PAYGATE_TIER_NOT_PAID

    if (
        normalized.endswith("-4k")
        or normalized.endswith("_4k")
        or "_ultra" in normalized
    ):
        return PAYGATE_TIER_TWO

    if normalized.endswith("-2k") or normalized.endswith("_1080p"):
        return PAYGATE_TIER_ONE

    return PAYGATE_TIER_NOT_PAID


def supports_model_for_tier(
    model_name: Optional[str], user_paygate_tier: Optional[str]
) -> bool:
    """Check whether the current account tier can use the given model."""
    required_tier = get_required_paygate_tier_for_model(model_name)
    return get_paygate_tier_rank(user_paygate_tier) >= get_paygate_tier_rank(
        required_tier
    )
