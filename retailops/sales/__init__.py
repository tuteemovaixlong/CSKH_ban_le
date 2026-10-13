"""RetailOps Sales Event Simulator & Ingestion Boundary package."""
from retailops.sales.events import (
    CANONICAL_FIELDS,
    VALID_STATUSES,
    INTERNAL_STATUS_MAPPING,
    compute_signature,
    sign_event,
    verify_event_signature,
    validate_event_schema,
    validate_timestamp,
    parse_timestamp,
)
from retailops.sales.simulator import SalesSimulator, DEFAULT_DEV_SECRET
from retailops.sales.adapter import SalesImportAdapter, ImportResult
from retailops.sales.fixtures import get_signed_fixtures

__all__ = [
    "CANONICAL_FIELDS",
    "VALID_STATUSES",
    "INTERNAL_STATUS_MAPPING",
    "compute_signature",
    "sign_event",
    "verify_event_signature",
    "validate_event_schema",
    "validate_timestamp",
    "parse_timestamp",
    "SalesSimulator",
    "DEFAULT_DEV_SECRET",
    "SalesImportAdapter",
    "ImportResult",
    "get_signed_fixtures",
]
