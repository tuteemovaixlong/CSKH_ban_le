"""Construct configured model gateways without probing endpoints or starting inference."""
from dataclasses import dataclass, field
from typing import Protocol

from retailops.config import Settings
from retailops_agent import RemoteAgent
from retailops_baseline import ModelConfig
from retailops_providers import OpenRouterAgent


class ModelGateway(Protocol):
    def inspect(self) -> dict: ...
    def chat(self, messages: list, allow_tools: bool, timeout: float) -> dict: ...


@dataclass(frozen=True)
class ModelGateways:
    custom: ModelGateway | None = field(default=None, repr=False)
    api: ModelGateway | None = field(default=None, repr=False)


def build_gateways(settings: Settings) -> ModelGateways:
    custom = None
    if settings.custom_enabled:
        custom = RemoteAgent(ModelConfig(model=settings.model, base_url=settings.model_url),
                             allowed_host=settings.allowed_host, token=settings.inference_token)
    api = OpenRouterAgent(settings.api_key, settings.api_model) if settings.api_enabled else None
    return ModelGateways(custom, api)
