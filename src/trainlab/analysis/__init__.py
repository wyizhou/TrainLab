"""Third-layer analysis package.

This package intentionally contains only the A3-01 boundary scaffold.  It does
not expose an analysis API, access SQLite, start subprocesses, or call Codex,
Garmin, Gmail, or any legacy TrainLab workflow.
"""

from .boundary import (
    AnalysisBoundaryError,
    AnalysisModuleManifest,
    build_module_manifest,
    verify_contract_snapshot,
    verify_import_boundary,
)
from .contracts import AnalysisReceipt, AnalysisRequest
from .config import AnalysisConfig, AnalysisConfigurationError, load_analysis_config
from .harness import HarnessBundle, HarnessResolutionError, SchemaEvidence, resolve_harness_bundle
from .service import AnalysisTool
from .features import FeatureError, FeatureLibrary
from .safety_rules import (
    SafetyRuleError,
    TrainingSafetyRuleEngine,
    evaluate_training_safety,
)
from .context import (
    AnalysisContextBuilder,
    ContextBuildError,
    ContextBuildRequest,
    ContextBuildResult,
    ContextSource,
    TechnicalSampleRequest,
    load_context_source,
    parse_canonical_context_json,
    validate_analysis_context,
)

__all__ = [
    "AnalysisBoundaryError",
    "AnalysisModuleManifest",
    "build_module_manifest",
    "verify_contract_snapshot",
    "verify_import_boundary",
    "AnalysisReceipt",
    "AnalysisRequest",
    "AnalysisTool",
    "AnalysisConfig",
    "AnalysisConfigurationError",
    "load_analysis_config",
    "HarnessBundle",
    "HarnessResolutionError",
    "SchemaEvidence",
    "resolve_harness_bundle",
    "FeatureError",
    "FeatureLibrary",
    "SafetyRuleError",
    "TrainingSafetyRuleEngine",
    "evaluate_training_safety",
    "AnalysisContextBuilder",
    "ContextBuildError",
    "ContextBuildRequest",
    "ContextBuildResult",
    "ContextSource",
    "TechnicalSampleRequest",
    "load_context_source",
    "parse_canonical_context_json",
    "validate_analysis_context",
]
