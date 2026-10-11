"""Content intelligence: the research layer, as typed artifacts.

The chain this package exists to make explicit::

    ResearchRequest -> ResearchResult -> Source -> Evidence -> Claim
                                                    |
                                                    +-> ClaimEvidenceLink

Each arrow is a model with its own validation, so no stage has to be trusted to
carry a fact forward correctly. Submodules keep the four concerns apart:

* :mod:`~manorem_ai.research.models` -- the vocabulary: what a source, a span, a
  claim and a support relationship *are*.
* :mod:`~manorem_ai.research.providers` and
  :mod:`~manorem_ai.research.brave` -- how sources are retrieved, behind one
  provider-neutral seam with two offline backends and one real, opt-in one.
* :mod:`~manorem_ai.research.evidence` -- turning a citation into a located span,
  and a typed span into a support relation.
* :mod:`~manorem_ai.research.validate` and :mod:`~manorem_ai.research.artifacts`
  -- what is checked, what is reported (``RES8xx``), and what is written down.

Re-exported here so ``from manorem_ai.research import ...`` keeps working exactly
as it did when this was a single module.
"""

from __future__ import annotations

from manorem_ai.research.artifacts import (
    ResearchManifest,
    SourceArtifactRef,
    store_source_artifacts,
    write_research_artifacts,
)
from manorem_ai.research.brave import BraveResearchProvider, html_to_text
from manorem_ai.research.evidence import (
    apply_assessment,
    classify_locator,
    extract_evidence,
    locate_quote,
)
from manorem_ai.research.models import (
    AssessmentEntry,
    Claim,
    ClaimEvidenceLink,
    ClaimImportance,
    ClaimStatus,
    ClaimType,
    Document,
    Entity,
    Evidence,
    EvidenceAssessment,
    EvidenceRelation,
    Locator,
    LocatorKind,
    ResearchBrief,
    ResearchRequest,
    ResearchResult,
    RetrievedSource,
    Source,
    SourceRef,
    VisualCandidate,
    derive_status,
    evidence_id,
    research_cache_key,
    source_identity,
)
from manorem_ai.research.providers import (
    CassetteResearchProvider,
    FixtureResearchProvider,
    ResearchError,
    ResearchProvider,
    StubResearchProvider,
)
from manorem_ai.research.validate import (
    RESEARCH_REPAIR_CODES,
    ProvenanceValidator,
    ResearchValidator,
)

__all__ = [
    "RESEARCH_REPAIR_CODES",
    "AssessmentEntry",
    "BraveResearchProvider",
    "CassetteResearchProvider",
    "Claim",
    "ClaimEvidenceLink",
    "ClaimImportance",
    "ClaimStatus",
    "ClaimType",
    "Document",
    "Entity",
    "Evidence",
    "EvidenceAssessment",
    "EvidenceRelation",
    "FixtureResearchProvider",
    "Locator",
    "LocatorKind",
    "ProvenanceValidator",
    "ResearchBrief",
    "ResearchError",
    "ResearchManifest",
    "ResearchProvider",
    "ResearchRequest",
    "ResearchResult",
    "ResearchValidator",
    "RetrievedSource",
    "Source",
    "SourceArtifactRef",
    "SourceRef",
    "StubResearchProvider",
    "VisualCandidate",
    "apply_assessment",
    "classify_locator",
    "derive_status",
    "evidence_id",
    "extract_evidence",
    "html_to_text",
    "locate_quote",
    "research_cache_key",
    "source_identity",
    "store_source_artifacts",
    "write_research_artifacts",
]
