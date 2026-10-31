"""Authenticated session boundary. HTTP never chooses a customer or workspace path."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ContextManager, Protocol

from retailops.business.permissions import ACTIVE_BUSINESS_ROLES, ROLE_PERMISSIONS

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
    membership_id: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class RequestContext:
    """Immutable per-request identity and authorization context."""
    customer_id: str
    role: str
    permissions: frozenset[str]
    tenant_id: str | None = None
    principal_id: str | None = None
    membership_id: str | None = None
    display_name: str | None = None
    workspace_id: str | None = None
    session_scope: str = 'synthetic-demo'
    data_mode: str = 'synthetic-demo'
    authenticated_session: bool = False

    @classmethod
    def from_binding(
        cls,
        binding: SessionBinding,
        *,
        session_scope: str = 'synthetic-demo',
        data_mode: str | None = None,
    ) -> RequestContext:
        app = binding.application
        role = str(binding.role or getattr(app, 'role', 'customer') or '').strip()
        permissions = (
            ROLE_PERMISSIONS.get(role, frozenset())
            if role in ACTIVE_BUSINESS_ROLES
            else frozenset()
        )
        tenant_id = binding.tenant_id
        if tenant_id is None:
            raw_tid = getattr(app, 'tenant_id', None)
            tenant_id = raw_tid if raw_tid and raw_tid != 'default' else None
        resolved_mode = data_mode or getattr(app, 'data_mode', 'synthetic-demo') or 'synthetic-demo'
        is_persistent_auth = bool(binding.principal_id and binding.membership_id and tenant_id)
        return cls(
            customer_id=binding.customer_id,
            role=role,
            permissions=permissions,
            tenant_id=tenant_id,
            principal_id=binding.principal_id,
            membership_id=binding.membership_id,
            display_name=binding.display_name,
            workspace_id=binding.workspace_id,
            session_scope=session_scope,
            data_mode=resolved_mode,
            authenticated_session=is_persistent_auth,
        )

    @classmethod
    def from_app(
        cls,
        app: Application,
        customer_id: str,
        *,
        session_scope: str = 'synthetic-demo',
        data_mode: str | None = None,
        authenticated_session: bool = False,
    ) -> RequestContext:
        role = str(getattr(app, 'role', 'customer') or '').strip()
        permissions = (
            ROLE_PERMISSIONS.get(role, frozenset())
            if role in ACTIVE_BUSINESS_ROLES
            else frozenset()
        )
        raw_tid = getattr(app, 'tenant_id', None)
        tenant_id = raw_tid if raw_tid and raw_tid != 'default' else None
        principal_id = getattr(app, 'principal_id', None)
        membership_id = getattr(getattr(app, 'quota_store', None), 'membership_id', None)
        resolved_mode = data_mode or getattr(app, 'data_mode', 'synthetic-demo') or 'synthetic-demo'
        return cls(
            customer_id=customer_id,
            role=role,
            permissions=permissions,
            tenant_id=tenant_id,
            principal_id=principal_id,
            membership_id=membership_id,
            display_name=getattr(app, 'display_name', None),
            workspace_id=None,
            session_scope=session_scope,
            data_mode=resolved_mode,
            authenticated_session=authenticated_session,
        )


class SessionBackend(Protocol):
    cookie_name: str
    session_seconds: int
    data_mode: str

    def login(self, token: str) -> str: ...
    def resolve(self, header: str) -> ContextManager[SessionBinding]: ...
    def logout(self, header: str) -> None: ...
    def check_health(self) -> None: ...
    def metadata(self) -> dict: ...
