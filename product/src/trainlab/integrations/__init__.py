"""Stable shared boundaries for TrainLab's provider integrations.

Feature layers import provider-neutral primitives from this package rather
than reaching into another feature layer's implementation.
"""

from .gmail_delivery import (
    GmailDeliveryError,
    GmailDeliveryGateway,
    GmailDeliveryReceipt,
    canonical_self_recipient,
)
from .project_config import ProjectConfigurationError, configured_recipient_email

__all__ = [
    "GmailDeliveryError",
    "GmailDeliveryGateway",
    "GmailDeliveryReceipt",
    "ProjectConfigurationError",
    "canonical_self_recipient",
    "configured_recipient_email",
]
