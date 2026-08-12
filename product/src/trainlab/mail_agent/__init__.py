"""Fourth-layer mail-agent public boundary.

This package intentionally contains no Gmail, Codex, database, polling, or
delivery implementation.  Those behaviours are introduced by later M4 units.
"""

from .contracts import (
    MAIL_RECEIPT_SCHEMA_VERSION,
    MAIL_REQUEST_SCHEMA_VERSION,
    MailCounts,
    MailReceipt,
    MailRequest,
    MailTool,
    exit_code_for_status,
)
from .context import ContextBuildResult, MailContextBuilder, MailContextError
from .runner import (
    AcceptedRecord,
    AcceptedStore,
    MailCodexRunner,
    MailGeneration,
    MailHarnessResolver,
    MailRejection,
    MailResultValidator,
    MailRunnerError,
    MemoryAcceptedStore,
)
from .fact_gate import (
    ActiveFactEvidence,
    AnalysisDependencyEvidence,
    FactGate,
    FactGateDecision,
    FactGateError,
    FactGateEvidence,
    GatedEvent,
    GatedFact,
    MailFactGate,
    MailFactGateError,
    bind_reason_event,
)
from .application import (
    MailApplicationError,
    MailApplicationPolicy,
    MailApplicationService,
    MailApplicationStages,
    UnavailableMailApplicationService,
)

__all__ = [
    "MAIL_RECEIPT_SCHEMA_VERSION",
    "MAIL_REQUEST_SCHEMA_VERSION",
    "MailCounts",
    "MailReceipt",
    "MailRequest",
    "MailTool",
    "exit_code_for_status",
    "ContextBuildResult",
    "MailContextBuilder",
    "MailContextError",
    "AcceptedRecord",
    "AcceptedStore",
    "MailCodexRunner",
    "MailGeneration",
    "MailHarnessResolver",
    "MailRejection",
    "MailResultValidator",
    "MailRunnerError",
    "MemoryAcceptedStore",
    "ActiveFactEvidence",
    "AnalysisDependencyEvidence",
    "FactGate",
    "FactGateDecision",
    "FactGateError",
    "FactGateEvidence",
    "GatedEvent",
    "GatedFact",
    "MailFactGate",
    "MailFactGateError",
    "bind_reason_event",
    "MailApplicationError",
    "MailApplicationPolicy",
    "MailApplicationService",
    "MailApplicationStages",
    "UnavailableMailApplicationService",
]
