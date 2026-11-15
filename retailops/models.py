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
    if settings.custom_enabled and settings.custom_api_endpoint:
        # Same two-layer OpenAI gateway as the API slot, with the custom slot's own endpoint and keys.
        custom = OpenRouterAgent(
            settings.custom_api_key,
            settings.model,
            tunnel_token=settings.custom_api_tunnel_token,
            endpoint=settings.custom_api_endpoint,
            vision=False,
        )
    elif settings.custom_enabled:
        custom = RemoteAgent(ModelConfig(model=settings.model, base_url=settings.model_url),
                             allowed_host=settings.allowed_host, token=settings.inference_token)
    api = (
        OpenRouterAgent(
            settings.api_key,
            settings.api_model,
            tunnel_token=settings.api_tunnel_token,
            endpoint=settings.api_endpoint or None,
            vision=settings.api_vision,
        )
        if settings.api_enabled
        else None
    )
    return ModelGateways(custom, api)
