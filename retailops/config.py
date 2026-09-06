"""Validated startup configuration. Secret values never appear in repr or summaries."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from retailops.core import DATA_MODE, ROOT, VERSION


def public_origin(value):
    parsed = urlsplit(value)
    hostname = parsed.hostname or ''
    if (value != 'https://' + hostname or parsed.scheme != 'https' or parsed.netloc != hostname
            or parsed.path or parsed.query or parsed.fragment or len(hostname) > 253 or '.' not in hostname
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in hostname.split('.'))):
        raise ValueError('RETAILOPS_PUBLIC_ORIGIN must be https:// followed by a lowercase DNS hostname, with no path or port.')
    return value


def flag(env, name):
    value = env.get(name, 'false').lower()
    if value not in ('true', 'false'):
        raise ValueError(name + ' must be true or false.')
    return value == 'true'


def integer(env, name, default, minimum, maximum):
    try:
        value = int(env.get(name, str(default)))
    except (TypeError, ValueError):
        raise ValueError(name + ' must be an integer.') from None
    if not minimum <= value <= maximum:
        raise ValueError(name + f' must be between {minimum} and {maximum}.')
    return value


@dataclass(frozen=True)
class Settings:
    interface: str
    output: Path
    access_token: str = field(repr=False)
    data_mode: str = DATA_MODE
    origin: str = ''
    bind: str = '127.0.0.1'
    port: int = 8000
    custom_enabled: bool = False
    model: str = 'qwen3.5:4b'
    model_url: str = field(default='', repr=False)
    allowed_host: str = field(default='', repr=False)
    inference_token: str = field(default='', repr=False)
    api_enabled: bool = False
    api_key: str = field(default='', repr=False)
    api_model: str = 'meta/muse-spark-1.3-contributor'
    api_daily_turn_limit: int = 20

    def __post_init__(self):
        if self.interface not in ('public', 'private'):
            raise ValueError('Interface must be public or private.')
        if self.data_mode not in (DATA_MODE, 'persistent-demo'):
            raise ValueError('Data mode must be synthetic-demo or persistent-demo; real customer data is not supported yet.')
        if self.data_mode == 'persistent-demo' and self.interface != 'public':
            raise ValueError('Persistent accounts require the public HTTPS interface.')
        if self.data_mode == DATA_MODE and not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', self.access_token):
            name = 'RETAILOPS_PUBLIC_INVITE_TOKEN' if self.interface == 'public' else 'RETAILOPS_DEMO_TOKEN'
            raise ValueError(name + ' must be a random 32–128 character URL-safe value.')
        if self.interface == 'public':
            public_origin(self.origin)
        if type(self.api_daily_turn_limit) is not int or not 1 <= self.api_daily_turn_limit <= 10000:
            raise ValueError('RETAILOPS_API_DAILY_TURN_LIMIT must be between 1 and 10000.')
        if type(self.port) is not int or not 0 <= self.port <= 65535:
            raise ValueError('RETAILOPS_API_PORT must be between 0 and 65535.')

    @classmethod
    def from_environment(cls, interface, environ: Mapping[str, str] | None = None):
        if interface not in ('public', 'private'):
            raise ValueError('Interface must be public or private.')
        env = os.environ if environ is None else environ
        public = interface == 'public'
        return cls(
            interface=interface,
            output=Path(env.get('RETAILOPS_OUTPUT', '/data' if public else str(ROOT/'artifacts'))),
            access_token=env.get('RETAILOPS_PUBLIC_INVITE_TOKEN' if public else 'RETAILOPS_DEMO_TOKEN', ''),
            data_mode=env.get('RETAILOPS_DATA_MODE', DATA_MODE),
            origin=env.get('RETAILOPS_PUBLIC_ORIGIN', '') if public else '',
            bind=env.get('RETAILOPS_API_BIND', '127.0.0.1') if not public else '0.0.0.0',
            port=integer(env, 'RETAILOPS_API_PORT', 8000, 0, 65535) if not public else 8000,
            custom_enabled=flag(env, 'RETAILOPS_PUBLIC_CUSTOM_ENABLED' if public else 'RETAILOPS_MODEL_ENABLED'),
            model=env.get('RETAILOPS_MODEL', 'qwen3.5:4b'),
            model_url=env.get('RETAILOPS_MODEL_URL', ''),
            allowed_host=env.get('RETAILOPS_ALLOWED_HOST', ''),
            inference_token=env.get('RETAILOPS_INFERENCE_TOKEN', ''),
            api_enabled=flag(env, 'RETAILOPS_API_ENABLED'),
            api_key=env.get('OPENROUTER_API_KEY', ''),
            api_model=env.get('RETAILOPS_API_MODEL', 'meta/muse-spark-1.3-contributor'),
            api_daily_turn_limit=integer(env, 'RETAILOPS_API_DAILY_TURN_LIMIT', 20, 1, 10000),
        )

    def summary(self):
        return {'version': VERSION, 'interface': self.interface, 'data_mode': self.data_mode,
                'custom_enabled': self.custom_enabled, 'api_enabled': self.api_enabled,
                'api_daily_turn_limit': self.api_daily_turn_limit}
