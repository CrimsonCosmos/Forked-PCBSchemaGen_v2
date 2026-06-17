"""Structured verification error types for PCBSchemaGen.

Replaces flat string errors with typed, categorized error objects
that support adaptive feedback, continuous reward, and recurrence tracking.
"""

from dataclasses import dataclass, field
from typing import Optional


# --- Error Phase ---
PHASE_SYNTAX = "syntax"
PHASE_ERC = "erc"
PHASE_KG = "phase2_kg"
PHASE_RULE = "phase3_rule"
PHASE_SI = "phase4_si"
PHASE_SYSTEM = "phase5_system"

# --- Severity ---
SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"

# --- Error Categories ---
# Phase 2 (KG constraints)
CAT_UNCONNECTED_PIN = "unconnected_pin"
CAT_SUPPLY_MISSING = "supply_missing"
CAT_SUPPLY_SHORT = "supply_short"
CAT_GATE_FLOATING = "gate_floating"
CAT_KELVIN_VIOLATION = "kelvin_violation"
CAT_KELVIN_SHORT = "kelvin_short"
CAT_DIFFERENTIAL_SHORT = "differential_short"
CAT_VREF_GND_SHORT = "vref_gnd_short"
CAT_MOSFET_PIN_UNCONNECTED = "mosfet_pin_unconnected"
CAT_DECOUPLING_MISSING = "decoupling_missing"
CAT_BOOTSTRAP_MISSING = "bootstrap_missing"
CAT_DRIVING_PAIR = "driving_pair_violation"
CAT_OUTPUT_RESISTOR_MISSING = "output_resistor_missing"
CAT_PIN_FLOATING = "pin_floating"

# Phase 3 (Rule checking)
CAT_CAP_DIRECT_MISSING = "cap_direct_missing"
CAT_R_PATH_MISSING = "r_path_missing"
CAT_L_PATH_MISSING = "l_path_missing"
CAT_RULE_MISMATCH = "rule_mismatch"

# Phase 4 (SI / skeleton)
CAT_COMPONENT_COUNT = "component_count_mismatch"
CAT_TOPOLOGY_MISMATCH = "topology_mismatch"
CAT_MISSING_COMPONENT = "missing_component"
CAT_EXTRA_COMPONENT = "extra_component"

# Phase 5 (System / complex task)
CAT_REQUIRED_COMPONENT_MISSING = "required_component_missing"
CAT_SYSTEM_TOPOLOGY = "system_topology_violation"

# Syntax / ERC
CAT_SYNTAX_ERROR = "syntax_error"
CAT_RUNTIME_ERROR = "runtime_error"
CAT_ERC_UNCONNECTED = "erc_unconnected"
CAT_ERC_CONFLICT = "erc_conflict"
CAT_NO_CODE_BLOCK = "no_code_block"


@dataclass
class VerificationError:
    """A single structured verification error."""

    phase: str
    severity: str
    category: str
    message: str
    component: Optional[str] = None
    pin: Optional[str] = None
    net: Optional[str] = None
    constraint: Optional[str] = None
    suggestion: Optional[str] = None
    recurrent: bool = False

    def __str__(self) -> str:
        """Backward-compatible string representation (matches old flat format)."""
        return self.message

    def fingerprint(self) -> str:
        """Unique error signature for recurrence tracking across attempts."""
        return f"{self.phase}:{self.category}:{self.component or ''}:{self.pin or ''}"

    def to_feedback(self, include_suggestion: bool = True) -> str:
        """Generate human/LLM-readable feedback string."""
        parts = [f"[{self.severity.upper()}] {self.message}"]
        if self.recurrent:
            parts.append("  [!] This error persisted from a previous attempt.")
        if include_suggestion and self.suggestion:
            parts.append(f"  -> Suggestion: {self.suggestion}")
        return "\n".join(parts)


# --- Reward Thresholds ---
# Used by compute_verification_reward()
REWARD_NO_CODE = 0.0
REWARD_HAS_CODE = 0.1
REWARD_SYNTAX_OK = 0.3
REWARD_ERC_OK = 0.5
REWARD_KG_OK = 0.7
REWARD_RULES_OK = 0.9
REWARD_PASS = 1.0


def compute_reward_from_errors(
    has_code: bool,
    syntax_ok: bool,
    erc_ok: bool,
    kg_errors: list,
    rule_errors: list,
    si_errors: list,
) -> float:
    """Compute continuous verification reward from error lists.

    Returns a float in [0, 1] reflecting how far through the
    verification pipeline the generated code reached.
    """
    if not has_code:
        return REWARD_NO_CODE
    if not syntax_ok:
        return REWARD_HAS_CODE
    if not erc_ok:
        return REWARD_SYNTAX_OK

    # Passed ERC - now check topology phases
    if kg_errors:
        # Partial credit: fewer KG errors = closer to 0.7
        max_kg = 10  # normalization cap
        ratio = min(len(kg_errors), max_kg) / max_kg
        return REWARD_ERC_OK + (REWARD_KG_OK - REWARD_ERC_OK) * (1 - ratio)

    if rule_errors:
        max_rule = 5
        ratio = min(len(rule_errors), max_rule) / max_rule
        return REWARD_KG_OK + (REWARD_RULES_OK - REWARD_KG_OK) * (1 - ratio)

    if si_errors:
        return REWARD_RULES_OK

    return REWARD_PASS
