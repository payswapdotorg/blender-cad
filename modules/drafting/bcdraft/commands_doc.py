"""UNDO / REDO — document undo stack commands (contract §5).

These commands take no prompts: they call ``document.undo()/redo()`` and
sink feedback about the remaining depth (ux-spec §3.10). Because they never
ask for input they run to completion headless without any provider.
"""

from __future__ import annotations

from bccmd import CommandContext, CommandResult, CommandSpec, Runner


def undo_run(ctx: CommandContext, runner: Runner) -> CommandResult:
    doc = ctx.document
    if doc.undo():
        depth = doc.undo_depth()
        summary = f"UNDO: one step undone, {depth} step(s) left"
    else:
        summary = "UNDO: everything has been undone"
    ctx.feedback(summary)
    return CommandResult(status="ok", summary=summary)


def redo_run(ctx: CommandContext, runner: Runner) -> CommandResult:
    doc = ctx.document
    if doc.redo():
        depth = doc.redo_depth()
        summary = f"REDO: one step redone, {depth} step(s) left"
    else:
        summary = "REDO: nothing to redo"
    ctx.feedback(summary)
    return CommandResult(status="ok", summary=summary)


UNDO = CommandSpec(
    name="UNDO", aliases=["U"], run=undo_run,
    help="Undo the last committed transaction",
)
REDO = CommandSpec(
    name="REDO", aliases=[], run=redo_run,
    help="Redo one undone transaction",
)

COMMANDS = (UNDO, REDO)
