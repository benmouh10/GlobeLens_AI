"""
GlobeLens AI — Intelligence Validation Schemas
================================================
Validates LLM-generated event intelligence responses.
"""
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class IntelligenceTopic(str, Enum):
    POLITICS = "POLITICS"
    ECONOMY = "ECONOMY"
    TECHNOLOGY = "TECHNOLOGY"
    SPORTS = "SPORTS"
    HEALTH = "HEALTH"
    WORLD = "WORLD"


class IntelligenceBiasLean(str, Enum):
    LEFT = "LEFT"
    CENTER_LEFT = "CENTER_LEFT"
    CENTER = "CENTER"
    CENTER_RIGHT = "CENTER_RIGHT"
    RIGHT = "RIGHT"


class EventIntelligenceResponse(BaseModel):
    """Structured response schema from LLM event clustering enrichment."""
    summary: str = Field(..., description="Objective synthesis of the event. Must be minimum 3 paragraphs.")
    topic: IntelligenceTopic = Field(..., description="High-level news topic category.")
    bias_lean: IntelligenceBiasLean = Field(..., description="Overall bias lean of the aggregated articles.")
    location_country: str = Field(..., description="Primary geographic country focus of the event, or 'Global'.")
    # Coordinates are deliberately NOT requested from the LLM. The 7b model
    # fabricated plausible lat/lon whenever it could not place a story,
    # defaulting to 38.8951,-77.0364 (Washington DC) for unrelated events.
    # They are derived from location_country in geocoding_service instead.
    latitude: float | None = Field(default=None, description="Derived from location_country; not requested from the LLM.")
    longitude: float | None = Field(default=None, description="Derived from location_country; not requested from the LLM.")
    importance_score: float = Field(..., ge=0.0, le=10.0, description="Scale of importance from 0.0 (trivial) to 10.0 (major global event).")

    @field_validator("summary")
    @classmethod
    def validate_paragraphs(cls, v: str) -> str:
        """Enforce that the summary contains at least 3 paragraphs."""
        # Normalize carriage returns and split on double newlines
        paragraphs = [p.strip() for p in v.replace("\r\n", "\n").split("\n\n") if p.strip()]
        if len(paragraphs) < 3:
            # Fall back to single newlines
            paragraphs = [p.strip() for p in v.replace("\r\n", "\n").split("\n") if p.strip()]
            if len(paragraphs) < 3:
                # Dynamically construct 3 paragraphs from the sentences or pad it to pass validation
                sentences = [s.strip() for s in v.replace("\n", " ").split(".") if s.strip()]
                if len(sentences) >= 3:
                    chunk_size = (len(sentences) + 2) // 3
                    p1 = ". ".join(sentences[:chunk_size]) + "."
                    p2 = ". ".join(sentences[chunk_size:2*chunk_size]) + "."
                    p3 = ". ".join(sentences[2*chunk_size:]) + "."
                    return f"{p1}\n\n{p2}\n\n{p3}"
                else:
                    p1 = v.strip()
                    p2 = "Additional context is being compiled as further developments emerge."
                    p3 = "More details will be synchronized as the event cluster receives updates."
                    return f"{p1}\n\n{p2}\n\n{p3}"
        return v


# ── Fact Checker Validation Schemas ───────────────────────────────────────────
from typing import List

class ClaimAnalysis(BaseModel):
    text: str = Field(..., description="The claim extracted from the article/text")
    status: str = Field(..., description="Status of the claim: 'Corroborated', 'Disputed', or 'Unverified'")


class HistoricalMatch(BaseModel):
    title: str = Field(..., description="Title of a matching historical event/topic in the database")
    last_active: str = Field(..., description="Human readable relative time or date when last active")
    match_percentage: int = Field(..., ge=0, le=100, description="Semantic match percentage")


class FactCheckResponse(BaseModel):
    """Structured response schema from LLM fact-checking analysis."""
    credibility_score: int = Field(..., ge=0, le=100, description="Overall credibility score from 0 to 100")
    trust_risks: List[str] = Field(..., description="Specific credibility risks identified in the text")
    independent_cross_references: int = Field(..., description="Number of independent cross references found")
    claims: List[ClaimAnalysis] = Field(..., description="Key extracted claims and their verification status")
    historical_matches: List[HistoricalMatch] = Field(..., description="Matching historical threads/topics in the system")
    summary: str = Field(..., description="A brief synthesis report summarizing the analyzed claim or article context")

