"""Infrastructure-independent Rule Registry, Module Loader, and Rule Executor."""

from __future__ import annotations

from collections.abc import Sequence

from made_core.domain.interfaces import DetectionModule, ModuleLoader, RuleExecutor, RuleRegistry
from made_core.domain.models import DetectionResult, EnrichedEvent


class RuleEngineError(Exception):
    """Base exception for deterministic Rule Engine failures."""


class DuplicateModuleRegistrationError(RuleEngineError):
    """Raised when an existing module identifier is registered again."""


class UnknownModuleError(RuleEngineError):
    """Raised when a requested module identifier is not registered."""


class ModuleExecutionError(RuleEngineError):
    """Raised when a detection module fails while handling an event."""


class InMemoryRuleRegistry(RuleRegistry):
    """In-memory registry of active modules, preserving registration order."""

    def __init__(self) -> None:
        self._modules: dict[str, DetectionModule] = {}

    def register(self, module: DetectionModule) -> None:
        if not isinstance(module, DetectionModule):
            raise TypeError("module must implement DetectionModule")

        module_id = module.get_module_id()
        if not module_id or not module_id.strip():
            raise ValueError("module identifier must be a non-empty string")
        if module_id in self._modules:
            raise DuplicateModuleRegistrationError(f"module '{module_id}' is already registered")
        self._modules[module_id] = module

    def get_active_module_ids(self) -> Sequence[str]:
        return tuple(self._modules)

    def contains(self, module_id: str) -> bool:
        return module_id in self._modules

    def get(self, module_id: str) -> DetectionModule:
        try:
            return self._modules[module_id]
        except KeyError as error:
            raise UnknownModuleError(f"module '{module_id}' is not registered") from error

    def get_registered_modules(self) -> Sequence[DetectionModule]:
        return tuple(self._modules.values())


class RegistryModuleLoader(ModuleLoader):
    """Resolves registered modules; it has no dynamic plugin behaviour."""

    def __init__(self, registry: InMemoryRuleRegistry) -> None:
        self._registry = registry

    def load(self, module_ids: Sequence[str]) -> Sequence[DetectionModule]:
        if module_ids is None:
            raise TypeError("module_ids must not be None")
        return tuple(self._registry.get(module_id) for module_id in module_ids)


class RuleEngineExecutor(RuleExecutor):
    """Sequentially orchestrates registered modules without detection logic."""

    def __init__(self, registry: RuleRegistry, loader: ModuleLoader) -> None:
        self._registry = registry
        self._loader = loader

    def execute(self, event: EnrichedEvent) -> Sequence[DetectionResult]:
        if event is None:
            raise TypeError("event must not be None")

        module_ids = self._registry.get_active_module_ids()
        modules = self._loader.load(module_ids)
        results: list[DetectionResult] = []

        for module in modules:
            try:
                results.append(module.detect(event))
            except Exception as error:
                module_id = module.get_module_id()
                raise ModuleExecutionError(f"module '{module_id}' failed during execution") from error

        return tuple(results)
