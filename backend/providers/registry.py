"""Provider registry – loads ``configs/providers.yaml`` (+ ``providers.local.yaml``)."""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any

from backend.core.config import deep_merge, load_yaml
from backend.core.errors import NotFoundError, ProviderDisabledError, ValidationError

from .base import ROLE_INTERFACES, BaseProvider, ProviderHealth, ProviderInfo

log = logging.getLogger("providers")


def _import_class(path: str) -> type:
    module_name, _, cls_name = path.partition(":")
    if not module_name or not cls_name:
        raise ValidationError(f"Invalid provider class path '{path}' (expected 'module:Class')")
    module = importlib.import_module(module_name)
    return getattr(module, cls_name)


class ProviderRegistry:
    def __init__(self, settings: Any, config: dict[str, Any] | None = None, configs_dir: Path | None = None) -> None:
        self.settings = settings
        configs_dir = configs_dir or settings.configs_dir
        if config is None:
            config = deep_merge(load_yaml(configs_dir / "providers.yaml"), load_yaml(configs_dir / "providers.local.yaml"))
        self.config = config
        self.defaults: dict[str, str] = dict(config.get("defaults", {}))
        self.infos: dict[str, ProviderInfo] = {}
        self._instances: dict[tuple[str, str], BaseProvider] = {}
        self._shared: dict[str, dict[str, Any]] = {}
        self._role_paths: dict[str, dict[str, str]] = {}
        for name, entry in (config.get("providers") or {}).items():
            self._add(name, entry)

    def _add(self, name: str, entry: dict[str, Any]) -> None:
        roles = entry.get("roles") or {}
        for role in roles:
            if role not in ROLE_INTERFACES:
                raise ValidationError(f"Provider '{name}': unknown role '{role}'")
        info = ProviderInfo(
            name=name,
            display_name=entry.get("display_name", name),
            description=" ".join(str(entry.get("description", "")).split()),
            location=entry.get("location", "local"),
            cost_model=entry.get("cost_model", "free"),
            unit_cost=float(entry.get("unit_cost", 0.0)),
            currency=entry.get("currency", "USD"),
            requires_api_key=bool(entry.get("requires_api_key", False)),
            api_key_env=entry.get("api_key_env"),
            # Cloud providers are disabled unless explicitly enabled.
            enabled=bool(entry.get("enabled", entry.get("location", "local") == "local")),
            explicit_only=bool(entry.get("explicit_only", False)),
            license_note=entry.get("license_note"),
            roles=list(roles),
        )
        self.infos[name] = info
        self._role_paths[name] = dict(roles)

    def register_instance(self, name: str, role: str, instance: BaseProvider, info: ProviderInfo | None = None) -> None:
        """Programmatic registration (tests, plugins)."""
        if info is not None:
            self.infos[name] = info
        elif name not in self.infos:
            self.infos[name] = instance.info
        if role not in self.infos[name].roles:
            self.infos[name].roles.append(role)
        self._instances[(name, role)] = instance

    # ---------------------------------------------------------------- lookup
    def api_key_present(self, info: ProviderInfo) -> bool:
        if not info.requires_api_key:
            return True
        return bool(info.api_key_env and os.environ.get(info.api_key_env))

    def names(self, role: str | None = None) -> list[str]:
        return [n for n, i in self.infos.items() if role is None or role in i.roles]

    def get(self, role: str, name: str | None = None, *, allow_disabled: bool = False) -> BaseProvider:
        name = name or self.defaults.get(role)
        if not name:
            raise NotFoundError(f"No default provider configured for role '{role}'")
        info = self.infos.get(name)
        if info is None:
            raise NotFoundError(f"Unknown provider '{name}'", details={"available": self.names(role)})
        if role not in info.roles:
            raise ValidationError(f"Provider '{name}' has no role '{role}'", details={"roles": info.roles})
        if not info.enabled and not allow_disabled:
            raise ProviderDisabledError(f"Provider '{name}' is disabled (configs/providers.local.yaml)")
        if info.requires_api_key and not self.api_key_present(info):
            raise ProviderDisabledError(
                f"Provider '{name}' requires the environment variable {info.api_key_env}"
            )
        key = (name, role)
        if key not in self._instances:
            cls = _import_class(self._role_paths[name][role])
            iface = ROLE_INTERFACES[role]
            if not issubclass(cls, iface):
                raise ValidationError(f"{cls.__name__} does not implement {iface.__name__}")
            shared = self._shared.setdefault(name, {})
            self._instances[key] = cls(info, self.settings, shared)
            log.info("Provider %s/%s initialised (%s)", name, role, cls.__name__)
        return self._instances[key]

    def set_enabled(self, name: str, enabled: bool) -> ProviderInfo:
        info = self.infos.get(name)
        if info is None:
            raise NotFoundError(f"Unknown provider '{name}'")
        if enabled and info.location == "cloud" and not self.api_key_present(info):
            raise ProviderDisabledError(f"Set {info.api_key_env} in .env before enabling '{name}'")
        info.enabled = enabled
        return info

    async def health(self, name: str) -> dict[str, ProviderHealth]:
        info = self.infos[name]
        out: dict[str, ProviderHealth] = {}
        for role in info.roles:
            if not info.enabled:
                out[role] = ProviderHealth(available=False, detail="deaktiviert")
                continue
            try:
                out[role] = await self.get(role, name).health()
            except Exception as exc:  # health must never raise
                out[role] = ProviderHealth(available=False, detail=str(exc))
        return out

    async def close(self) -> None:
        for inst in self._instances.values():
            try:
                await inst.close()
            except Exception:  # pragma: no cover
                log.exception("Error closing provider %s", inst.name)
