"""RetailOps v2 integration event contract and canonical ingestion package."""

from retailops.integration.contract import (
    ALL_EVENT_TYPES,
    CONTRACT_VERSION,
    ContractValidationError,
    INBOUND_EVENT_TYPES,
    REQUEST_EVENT_TYPES,
    W6_1B_1_SUPPORTED_EVENT_TYPES,
    ensure_w6_1b_1_supported_event,
    iso_vn_to_epoch,
    parse_iso_vn_timestamp,
    validate_event_v2,
)
from retailops.integration.ingest import (
    ImportResult,
    IntegrationIngestService,
    MIN_SECRET_KEY_BYTES,
    compute_payload_hmac_digest,
    read_regular_secret_file,
    redact_order_created_recipient,
)

__all__ = [
    "ALL_EVENT_TYPES",
    "CONTRACT_VERSION",
    "ContractValidationError",
    "INBOUND_EVENT_TYPES",
    "ImportResult",
    "IntegrationIngestService",
    "MIN_SECRET_KEY_BYTES",
    "REQUEST_EVENT_TYPES",
    "W6_1B_1_SUPPORTED_EVENT_TYPES",
    "compute_payload_hmac_digest",
    "ensure_w6_1b_1_supported_event",
    "iso_vn_to_epoch",
    "parse_iso_vn_timestamp",
    "read_regular_secret_file",
    "redact_order_created_recipient",
    "validate_event_v2",
]
