"""Command registry — contract §4.3 (m1-module-contracts.md).

Resolves commands by name-or-alias (case-insensitive), detects collisions,
runs commands through the prompt loop and records history. Also carries the
skills registration hook (glossary §4 inversion note): the ``skills``
package registers itself here at load time so the command line can expose
skill names — present but unused at M1.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .history import History
from .input import ScriptedProvider
from .spec import (
    Cancelled,
    CommandContext,
    CommandResult,
    CommandSpec,
    DuplicateCommand,
    Runner,
    UnknownCommand,
    _no_input_provider,
)


class Registry:
    """The command registry (one per application session)."""

    def __init__(self) -> None:
        self._specs: Dict[str, CommandSpec] = {}     # NAME -> spec
        self._aliases: Dict[str, str] = {}            # ALIAS -> NAME
        self._hooks: Dict[str, List[Callable]] = {}   # hook name -> callables

    # -- registration -------------------------------------------------------
    def register(self, spec: CommandSpec) -> None:
        """Register a command; duplicate name or alias raises DuplicateCommand."""
        key = spec.name.upper()
        if key in self._specs:
            raise DuplicateCommand(f"command name {key!r} already registered")
        if key in self._aliases:
            raise DuplicateCommand(f"name {key!r} collides with an existing alias")
        for alias in spec.aliases:
            alias_key = alias.upper()
            if alias_key in self._specs:
                raise DuplicateCommand(
                    f"alias {alias_key!r} for {key} collides with command name"
                )
            if alias_key in self._aliases:
                raise DuplicateCommand(
                    f"alias {alias_key!r} already used by {self._aliases[alias_key]}"
                )
        self._specs[key] = spec
        for alias in spec.aliases:
            self._aliases[alias.upper()] = key

    def register_hook(self, name: str, callback: Callable) -> None:
        """Skills registration hook (glossary §4 dependency-inversion note).

        Present but unused at M1: the ``skills`` package will call this to
        register skill-name handlers into the command line.
        """
        self._hooks.setdefault(name, []).append(callback)

    @property
    def hooks(self) -> Dict[str, List[Callable]]:
        """Read access to registered hooks (empty at M1 by design)."""
        return dict(self._hooks)

    # -- lookup -------------------------------------------------------------
    def lookup(self, token: str) -> Optional[CommandSpec]:
        """Resolve name-or-alias, case-insensitive; None when unknown."""
        if not isinstance(token, str):
            return None
        key = token.strip().upper()
        if key in self._specs:
            return self._specs[key]
        name = self._aliases.get(key)
        if name is not None:
            return self._specs[name]
        return None

    def names(self) -> List[str]:
        """Canonical command names in registration order."""
        return list(self._specs)

    def specs(self) -> List[CommandSpec]:
        return list(self._specs.values())

    def completions(self, prefix: str) -> List[str]:
        """Names + aliases matching a prefix (autocomplete support, ux-spec §3.1)."""
        prefix = (prefix or "").upper()
        tokens = list(self._specs) + list(self._aliases)
        return sorted(t for t in tokens if t.startswith(prefix) and t)

    def suggestions(self, prefix: str, limit: int = 8) -> List[tuple]:
        """Autocomplete suggestions — ``(name, help)`` pairs (M2 §3).

        Case-insensitive matching over canonical names AND aliases; an
        alias match reports its CANONICAL command name. Exact-prefix
        matches come first, then contains-matches; within each group the
        order is stable (canonical names in registration order, then
        aliases in alias-map order), deduplicated by canonical name, and
        the combined ranked list is truncated to ``limit``.

        An empty prefix matches everything, so it returns the first
        ``limit`` canonical names in registration order.
        """
        limit = max(int(limit), 0)
        text = (prefix or "").strip().upper()
        if limit == 0:
            return []
        if not text:
            return [(spec.name, spec.help)
                    for spec in self._specs.values()][:limit]

        ranked: List[tuple] = []
        seen: set = set()

        def _add(name: str, spec) -> None:
            if name not in seen:
                seen.add(name)
                ranked.append((spec.name, spec.help))

        # exact-prefix matches: canonical names first, then aliases
        for name, spec in self._specs.items():
            if name.startswith(text):
                _add(name, spec)
        for alias, name in self._aliases.items():
            if alias.startswith(text) and name not in seen:
                _add(name, self._specs[name])
        if len(ranked) >= limit:
            return ranked[:limit]
        # contains-matches (still prefix-ordered groups; canonical first)
        for name, spec in self._specs.items():
            if text in name and name not in seen:
                _add(name, spec)
        for alias, name in self._aliases.items():
            if text in alias and name not in seen:
                _add(name, self._specs[name])
        return ranked[:limit]

    # -- execution ----------------------------------------------------------
    def run_command(
        self,
        ctx: CommandContext,
        name: str,
        provider: Optional[Callable] = None,
    ) -> CommandResult:
        """Resolve ``name`` and drive it through the prompt loop.

        ``provider`` supplies ``Request -> InputValue``; when None the
        context's ``default_provider`` is used, and failing that the command
        cancels at its first prompt (headless no-input behavior).
        :class:`Cancelled` yields a clean ``status="cancelled"`` result.
        """
        spec = self.lookup(name)
        if spec is None:
            raise UnknownCommand(str(name))

        machine = ctx.machine
        machine.begin(spec.name)

        if provider is None:
            provider = getattr(ctx, "default_provider", None) or _no_input_provider
        runner = Runner(ctx, provider)

        try:
            result = spec.run(ctx, runner)
        except Cancelled:
            machine.cancel()
            result = CommandResult(
                status="cancelled", summary=f"{spec.name} cancelled"
            )
        except BaseException:
            # Unexpected failure: leave the machine idle, then re-raise.
            machine.cancel()
            raise
        else:
            if not isinstance(result, CommandResult):
                result = CommandResult(status="ok", summary=str(result))
            machine.commit()
            machine.finish()

        self.record(ctx, spec, result, runner.raw_inputs)
        return result

    # -- history ------------------------------------------------------------
    def record(
        self,
        ctx: CommandContext,
        spec: CommandSpec,
        result: CommandResult,
        raw_inputs: Optional[List[str]] = None,
    ) -> None:
        """Append one history entry (also used by the modal operator path)."""
        history: History = ctx.history
        if history is None:
            return
        history.append(
            command=spec.name,
            raw_inputs=list(raw_inputs or []),
            summary=result.summary,
            status=result.status,
        )
