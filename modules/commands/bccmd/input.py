"""Input parsing — AutoCAD-familiar text forms (contract §4.4, ux-spec §3.3).

Accepted point forms::

    "12,34"      absolute 2D      -> Point(12, 34, 0)
    "12,34,5"    absolute 3D      -> Point(12, 34, 5)
    "5<30"       absolute polar   -> Point from origin, 5 units at 30° CCW of +X
    "@3,4"       relative          -> last_point + (3, 4)
    "@3,4,5"     relative 3D       -> last_point + (3, 4, 5)
    "@"          last point        -> last_point (repeat)
    "@5<30"      relative polar    -> last_point + 5 units at 30°

Plain numbers resolve per request kind: ``"42"`` is 42 drawing units at a
distance prompt, 42 degrees at an angle prompt; at point prompts a lone
number is invalid (AutoCAD requires two coordinates).

Keywords match per the AutoCAD convention: prefix-insensitive where
unambiguous, case-insensitive, and the significant uppercase letters of an
option are shortcuts ("c" → "Close", "u" → "Undo", "e" → "Exit"). Ambiguous
input ("c" with options ["Copy", "Close"]) matches nothing and re-asks.

Empty input accepts ``request.default`` when present; at point/selection
prompts without a default it becomes the keyword "Enter" (Enter ends the
prompt — LINE/COPY use this to finish, ux-spec §3.3 "At 'Select objects:'
prompts: Enter ends selection").
"""

from __future__ import annotations

import math
from typing import Iterable, List, Optional

from .spec import Cancelled, CommandContext, InputValue, Point, Request


class InputParseError(ValueError):
    """Text could not be resolved for the current Request. Re-ask."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _number(text: str) -> float:
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise InputParseError(f"Invalid number: {text!r}") from None
    if math.isnan(value) or math.isinf(value):
        raise InputParseError(f"Invalid number: {text!r}")
    return value


def _coord_tuple(text: str) -> List[float]:
    parts = [p for p in text.split(",")]
    if len(parts) not in (2, 3) or any(p.strip() == "" for p in parts):
        raise InputParseError(f"Invalid coordinate: {text!r}")
    return [_number(p) for p in parts]


def polar(origin: Point, distance: float, angle_deg: float) -> Point:
    """``distance`` at ``angle_deg`` (CCW from +X) from ``origin``."""
    rad = math.radians(angle_deg)
    return Point(
        origin.x + distance * math.cos(rad),
        origin.y + distance * math.sin(rad),
        origin.z,
    )


def _keyword_matches(option: str, token: str) -> bool:
    """Prefix match or significant-uppercase shortcut match (case-insensitive)."""
    token_low = token.lower()
    if option.lower().startswith(token_low):
        return True
    significant = "".join(ch for ch in option if ch.isupper())
    return bool(significant) and significant.lower().startswith(token_low)


def match_keyword(token: str, options: Iterable[str]) -> Optional[str]:
    """Return the unique option matching ``token``; None on zero/multi match."""
    token = token.strip()
    if not token:
        return None
    matches = [o for o in options if _keyword_matches(o, token)]
    if len(matches) == 1:
        return matches[0]
    return None


# ---------------------------------------------------------------------------
# the parser
# ---------------------------------------------------------------------------

def parse(text: str, request: Request, last_point: Optional[Point] = None) -> InputValue:
    """Resolve one raw input string into an InputValue for ``request``.

    Raises :class:`InputParseError` on unresolvable text — the Runner re-asks
    with the same Request; parse errors never abort a command.
    """
    raw = text if isinstance(text, str) else str(text)
    token = raw.strip()

    if token == "":
        if request.default is not None:
            if isinstance(request.default, str):
                return InputValue(kind="keyword", value=request.default, raw=raw)
            return InputValue(kind=request.kind, value=request.default, raw=raw)
        if request.kind in ("point", "selection"):
            # Enter with no default: end-of-prompt keyword ("Enter ends selection")
            return InputValue(kind="keyword", value="Enter", raw=raw)
        raise InputParseError("no input")

    options = request.options or []

    # keyword first when the token cannot be a number/coordinate
    first = token[0]
    numeric_like = first.isdigit() or first in ".+-@"
    if not numeric_like:
        if options:
            matched = match_keyword(token, options)
            if matched is not None:
                return InputValue(kind="keyword", value=matched, raw=raw)
        if request.kind == "string":
            return InputValue(kind="string", value=token, raw=raw)
        if options:
            raise InputParseError(
                f"Ambiguous or unknown keyword: {token!r} "
                f"(options: {'/'.join(options)})"
            )
        raise InputParseError(f"Invalid input: {token!r}")

    # relative forms need the tracked last point
    if token.startswith("@"):
        body = token[1:].strip()
        if body == "":
            if last_point is None:
                raise InputParseError("No last point to repeat")
            return InputValue(kind="point", value=Point(last_point.x, last_point.y, last_point.z), raw=raw)
        if last_point is None:
            raise InputParseError(
                f"Relative input {token!r} requires a previous point"
            )
        if "<" in body:
            dist_part, _, angle_part = body.partition("<")
            return InputValue(
                kind="point",
                value=polar(last_point, _number(dist_part), _number(angle_part)),
                raw=raw,
            )
        coords = _coord_tuple(body)
        delta = Point(coords[0], coords[1], coords[2] if len(coords) == 3 else 0.0)
        return InputValue(kind="point", value=last_point + delta, raw=raw)

    # absolute polar "dist<ang"
    if "<" in token:
        dist_part, _, angle_part = token.partition("<")
        value = polar(Point(0.0, 0.0, 0.0), _number(dist_part), _number(angle_part))
        return _as_kind(value, request, last_point, raw)

    # plain number
    if "," not in token:
        number = _number(token)
        if request.kind == "point":
            raise InputParseError(
                "A point needs two coordinates (x,y) — got a single number"
            )
        return InputValue(kind=request.kind, value=number, raw=raw)

    # absolute coordinate
    coords = _coord_tuple(token)
    point = Point(coords[0], coords[1], coords[2] if len(coords) == 3 else 0.0)
    return _as_kind(point, request, last_point, raw)


def _as_kind(point: Point, request: Request, last_point: Optional[Point], raw: str) -> InputValue:
    """A coordinate entered at a distance/angle request resolves relative to
    the last point (point-in-direction entry, ux-spec §3.9.5 approximation)."""
    if request.kind == "point":
        return InputValue(kind="point", value=point, raw=raw)
    if request.kind in ("distance", "angle"):
        if last_point is None:
            raise InputParseError(
                "A point at this prompt needs a previous point as reference"
            )
        dx = point.x - last_point.x
        dy = point.y - last_point.y
        if request.kind == "distance":
            return InputValue(kind="distance", value=math.hypot(dx, dy), raw=raw)
        return InputValue(kind="angle", value=math.degrees(math.atan2(dy, dx)), raw=raw)
    if request.kind == "string":
        return InputValue(kind="string", value=str(point.to_tuple()), raw=raw)
    raise InputParseError(f"Coordinate not valid for {request.kind} prompt")


# ---------------------------------------------------------------------------
# InputValue factories (used by tests, scripted providers and the shell)
# ---------------------------------------------------------------------------

def point_input(x: float, y: float, z: float = 0.0) -> InputValue:
    return InputValue(kind="point", value=Point(float(x), float(y), float(z)))


def keyword_input(keyword: str) -> InputValue:
    return InputValue(kind="keyword", value=keyword)


def selection_input(ids: List[str]) -> InputValue:
    return InputValue(kind="selection", value=list(ids))


def distance_input(value: float) -> InputValue:
    return InputValue(kind="distance", value=float(value))


def angle_input(value: float) -> InputValue:
    return InputValue(kind="angle", value=float(value))


# ---------------------------------------------------------------------------
# ScriptedProvider — Request -> InputValue from a queue (tests + agents)
# ---------------------------------------------------------------------------

class ScriptedProvider:
    """Deterministic provider used by tests, the headless shell path and the
    acceptance battery.

    Queue items may be:
      * :class:`InputValue` — returned verbatim
      * ``str``              — parsed for the current Request (contract §4.4)
      * ``BaseException``    — raised (``Cancelled()`` aborts the command;
                                ``InputParseError`` exercises the re-ask loop)

    An exhausted queue raises :class:`Cancelled` (headless no-more-input).
    """

    def __init__(self, ctx: CommandContext, items: Iterable):
        self._ctx = ctx
        self._items = list(items)

    def __call__(self, request: Request) -> InputValue:
        if not self._items:
            raise Cancelled()
        item = self._items.pop(0)
        if isinstance(item, InputValue):
            return item
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            return parse(item, request, self._ctx.last_point)
        raise TypeError(
            f"ScriptedProvider accepts InputValue | str | exception, got {item!r}"
        )
