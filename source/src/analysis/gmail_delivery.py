"""Legacy import facade for the shared Gmail delivery boundary.

New code imports :mod:`src.integrations.gmail_delivery`.  This module is
retained so historical callers and persisted test seams keep their public
import path without keeping the transport owned by the analysis layer.
"""

from ..integrations.gmail_delivery import (
    GmailDeliveryClient,
    GmailDeliveryError,
    GmailDeliveryGateway,
    GmailDeliveryReceipt,
    canonical_self_recipient,
)

__all__ = [
    "GmailDeliveryClient",
    "GmailDeliveryError",
    "GmailDeliveryGateway",
    "GmailDeliveryReceipt",
    "canonical_self_recipient",
]
