"""
Pluggable deliverable quality scoring.

The validator produces a 0.0–1.0 quality score for a submitted deliverable.
In Phase 2 this is a configurable heuristic. In Phase 3 it can be replaced
by on-chain validated results or a third-party validation agent.
"""

import hashlib
import random
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class Deliverable:
    contract_id: str
    seller_id: str
    content: str                       # the actual work product (text/json/etc.)
    capability_type: str
    claimed_quality: float             # what the seller claims


@dataclass
class ValidationResult:
    score: float                        # 0.0–1.0
    passed: bool                        # score >= threshold
    threshold: float
    notes: str
    validator_id: str


class DeterministicValidator:
    """
    Scores deliverables based on content characteristics.
    Reproducible: same content always gets same score (deterministic).

    In a real implementation this would call specialist review agents
    or run test suites. For simulation purposes it scores based on
    length, structure, and the seller's true quality capability
    (injected from the persona's private state).
    """

    def __init__(self, seller_true_quality_map: dict[str, float]):
        self._quality_map = seller_true_quality_map

    def validate(
        self,
        deliverable: Deliverable,
        threshold: float,
        seed: Optional[int] = None,
    ) -> ValidationResult:
        true_quality = self._quality_map.get(deliverable.seller_id, 0.5)

        # Deterministic score: hash content for reproducibility + small variance
        content_hash = int(hashlib.md5(deliverable.content.encode()).hexdigest(), 16)
        rng = random.Random(seed or content_hash)

        # Score = true_quality ± small noise (±8%)
        noise = rng.uniform(-0.08, 0.08)
        score = max(0.0, min(1.0, true_quality + noise))

        passed = score >= threshold
        notes = (
            f"Quality score {score:.2f} vs threshold {threshold:.2f}. "
            f"{'Passed.' if passed else 'Failed — below threshold.'}"
        )
        return ValidationResult(
            score=round(score, 3),
            passed=passed,
            threshold=threshold,
            notes=notes,
            validator_id="deterministic_validator",
        )


class LengthHeuristicValidator:
    """
    Quick validator that scores based on deliverable length + structure.
    No access to true quality — purely observable signal.
    Useful for testing whether sellers game length to inflate scores.
    """

    MIN_CHARS = 200
    MAX_CHARS = 5000

    def validate(self, deliverable: Deliverable, threshold: float) -> ValidationResult:
        content = deliverable.content.strip()
        length_score = min(1.0, len(content) / self.MAX_CHARS)

        # Structural signals
        has_sections = content.count("\n") > 3
        has_numbers = any(c.isdigit() for c in content)
        structural_bonus = (0.05 if has_sections else 0) + (0.05 if has_numbers else 0)

        score = min(1.0, length_score + structural_bonus)
        passed = score >= threshold

        return ValidationResult(
            score=round(score, 3),
            passed=passed,
            threshold=threshold,
            notes=f"Length-based heuristic. Chars: {len(content)}. Sections: {has_sections}.",
            validator_id="length_heuristic",
        )


class AlwaysPassValidator:
    """Test fixture — passes everything. Use to isolate non-quality variables."""

    def validate(self, deliverable: Deliverable, threshold: float) -> ValidationResult:
        return ValidationResult(
            score=1.0, passed=True, threshold=threshold,
            notes="AlwaysPass — test fixture.", validator_id="always_pass",
        )


class AlwaysFailValidator:
    """Test fixture — fails everything. Use to test dispute and refund paths."""

    def validate(self, deliverable: Deliverable, threshold: float) -> ValidationResult:
        return ValidationResult(
            score=0.0, passed=False, threshold=threshold,
            notes="AlwaysFail — test fixture.", validator_id="always_fail",
        )


ValidatorFn = Callable[[Deliverable, float], ValidationResult]

VALIDATORS = {
    "deterministic": None,       # requires seller_true_quality_map — instantiated by runner
    "length_heuristic": LengthHeuristicValidator(),
    "always_pass": AlwaysPassValidator(),
    "always_fail": AlwaysFailValidator(),
}


def get_validator(name: str, seller_quality_map: Optional[dict] = None):
    if name == "deterministic":
        if not seller_quality_map:
            raise ValueError("deterministic validator requires seller_quality_map")
        return DeterministicValidator(seller_quality_map)
    if name not in VALIDATORS:
        raise ValueError(f"Unknown validator '{name}'. Choose from: {list(VALIDATORS)}")
    return VALIDATORS[name]
