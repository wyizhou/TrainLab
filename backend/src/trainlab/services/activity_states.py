PUBLIC_IMPORT_STATUSES = frozenset(
    {"pending", "processing", "complete", "partial", "failed", "deleting", "delete_failed"}
)
VISIBLE_ACTIVITY_STATUSES = frozenset({"complete", "partial"})
PARSE_RETRYABLE_STATUSES = frozenset({"pending", "failed", "partial"})
DELETE_RECOVERABLE_STATUSES = frozenset({"deleting", "delete_failed"})


def is_visible_activity_status(status: str) -> bool:
    return status in VISIBLE_ACTIVITY_STATUSES


def is_parse_retryable_status(status: str) -> bool:
    return status in PARSE_RETRYABLE_STATUSES


def is_delete_recovery_status(status: str) -> bool:
    return status in DELETE_RECOVERABLE_STATUSES
