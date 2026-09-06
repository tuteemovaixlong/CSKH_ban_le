"""Authenticated session boundary. HTTP never chooses a customer or workspace path."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ContextManager, Protocol

if TYPE_CHECKING:
    from retailops.business.application import Application


@dataclass(frozen=True)
class SessionBinding:
    application: Application = field(repr=False)
    customer_id: str
    workspace_id: str
    tenant_id: str | None = None
    principal_id: str | None = None
    display_name: str | None = None


class SessionBackend(Protocol):
    cookie_name: str
    session_seconds: int
    data_mode: str

    def login(self, token: str) -> str: ...
    def resolve(self, header: str) -> ContextManager[SessionBinding]: ...
    def logout(self, header: str) -> None: ...
    def check_health(self) -> None: ...
    def metadata(self) -> dict: ...
