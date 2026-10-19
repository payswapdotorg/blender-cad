"""Text and dimension style tables (contract: m2-module-contracts.md §2.6).

Two small record tables:

- :class:`TextStyleRecord` — name, height, width_factor;
- :class:`DimStyleRecord` — name, dimscale, dimtxt, dimasz, dimexo, dimexe.

"Standard" is always present in both tables (guarded on removal —
:class:`errors.ProtectedRecord`). The CURRENT style is not stored here at
all: it is the ``TEXTSTYLE`` / ``DIMSTYLE`` setting (contract §2.5), so
setting the current style goes through ``doc.settings.set(...)`` only
(small validator, binding).

Style table changes are document content: they require the open
transaction and journal the ops ``add_text_style`` / ``remove_text_style``
/ ``mutate_text_style`` (and the ``*_dim_style`` equivalents). Serialized
as ``"text_styles": [...]`` and ``"dim_styles": [...]`` in pinned record
key order.
"""

from __future__ import annotations

import math

from . import errors

#: Mutable fields of each record type, in serialization order.
TEXT_STYLE_FIELDS = ("height", "width_factor")
DIM_STYLE_FIELDS = ("dimscale", "dimtxt", "dimasz", "dimexo", "dimexe")

STANDARD = "Standard"


def _coerce_float(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number, got {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite, got {value!r}")
    return result


class TextStyleRecord:
    """Text style: name + height + width factor (contract §2.6)."""

    _FIELDS = TEXT_STYLE_FIELDS

    def __init__(self, name, height=2.5, width_factor=1.0):
        self.name = str(name)
        self.height = _coerce_float(height, "height")
        self.width_factor = _coerce_float(width_factor, "width_factor")

    def set(self, **changes) -> dict:
        for key in changes:
            if key not in self._FIELDS:
                raise ValueError(f"unknown text style property {key!r}")
        coerced = {key: _coerce_float(value, key) for key, value in changes.items()}
        prior = {key: getattr(self, key) for key in changes}
        for key, value in coerced.items():
            setattr(self, key, value)
        return prior

    def to_dict(self) -> dict:
        return {"name": self.name,
                "height": self.height,
                "width_factor": self.width_factor}

    def props_dict(self) -> dict:
        return {"height": self.height, "width_factor": self.width_factor}

    @classmethod
    def from_dict(cls, data: dict) -> "TextStyleRecord":
        if not isinstance(data, dict) or "name" not in data:
            raise ValueError(
                f"text style record must be a dict with a 'name', got {data!r}")
        kwargs = {key: data[key] for key in cls._FIELDS if key in data}
        return cls(data["name"], **kwargs)

    def copy(self) -> "TextStyleRecord":
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        return clone

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TextStyleRecord {self.name!r} height={self.height} width_factor={self.width_factor}>"


class DimStyleRecord:
    """Dimension style: name + the five pinned sizing fields (§2.6)."""

    _FIELDS = DIM_STYLE_FIELDS

    def __init__(self, name, dimscale=1.0, dimtxt=2.5, dimasz=2.5,
                 dimexo=0.625, dimexe=1.25):
        self.name = str(name)
        self.dimscale = _coerce_float(dimscale, "dimscale")
        self.dimtxt = _coerce_float(dimtxt, "dimtxt")
        self.dimasz = _coerce_float(dimasz, "dimasz")
        self.dimexo = _coerce_float(dimexo, "dimexo")
        self.dimexe = _coerce_float(dimexe, "dimexe")

    def set(self, **changes) -> dict:
        for key in changes:
            if key not in self._FIELDS:
                raise ValueError(f"unknown dim style property {key!r}")
        coerced = {key: _coerce_float(value, key) for key, value in changes.items()}
        prior = {key: getattr(self, key) for key in changes}
        for key, value in coerced.items():
            setattr(self, key, value)
        return prior

    def to_dict(self) -> dict:
        return {"name": self.name,
                "dimscale": self.dimscale,
                "dimtxt": self.dimtxt,
                "dimasz": self.dimasz,
                "dimexo": self.dimexo,
                "dimexe": self.dimexe}

    def props_dict(self) -> dict:
        return {key: getattr(self, key) for key in self._FIELDS}

    @classmethod
    def from_dict(cls, data: dict) -> "DimStyleRecord":
        if not isinstance(data, dict) or "name" not in data:
            raise ValueError(
                f"dim style record must be a dict with a 'name', got {data!r}")
        kwargs = {key: data[key] for key in cls._FIELDS if key in data}
        return cls(data["name"], **kwargs)

    def copy(self) -> "DimStyleRecord":
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        return clone

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<DimStyleRecord {self.name!r} dimscale={self.dimscale} "
                f"dimtxt={self.dimtxt} dimasz={self.dimasz} "
                f"dimexo={self.dimexo} dimexe={self.dimexe}>")


class _StyleTable:
    """Shared implementation for both style tables (name-keyed, ordered,
    transaction-gated, journaled)."""

    _KIND = "style"      # "text" | "dim" (error wording)
    _OP_PREFIX = "style"  # "text_style" | "dim_style" (journal op names)
    _RECORD_CLS = None

    @property
    def _FIELDS(self) -> tuple:
        return self._RECORD_CLS._FIELDS

    def __init__(self, document=None):
        self._doc = document
        self._records: dict = {}
        self._install_standard()

    def _install_standard(self) -> None:
        record = self._RECORD_CLS(STANDARD)  # class-default Standard record
        self._records[record.name] = record

    # -- reads -------------------------------------------------------------
    def names(self) -> list:
        return list(self._records)

    def get(self, name: str):
        return self._records.get(str(name))

    def records(self) -> list:
        return [record.copy() for record in self._records.values()]

    def __contains__(self, name) -> bool:
        return str(name) in self._records

    def __iter__(self):
        return iter(self.names())

    def __len__(self) -> int:
        return len(self._records)

    def __eq__(self, other) -> bool:
        if isinstance(other, (list, tuple)):
            return self.names() == list(other)
        if isinstance(other, _StyleTable):
            return self.names() == other.names()
        return NotImplemented

    __hash__ = None

    # -- mutations (transaction + journal required) --------------------------
    def add(self, name, **props):
        tx = self._doc._require_tx()
        name = str(name)
        if name in self._records:
            raise errors.DuplicateStyle(self._KIND, name)
        for key in props:
            if key not in self._FIELDS:
                raise ValueError(f"unknown {self._KIND} style property {key!r}")
        record = self._RECORD_CLS(name, **props)
        self._records[name] = record
        tx._record({"op": f"add_{self._OP_PREFIX}", "name": name,
                    "props": record.props_dict()})
        return record

    def mutate(self, name, **changes):
        tx = self._doc._require_tx()
        record = self._records.get(str(name))
        if record is None:
            raise errors.StyleNotFound(self._KIND, str(name))
        prior = record.set(**changes)  # validates everything first
        tx._record({"op": f"mutate_{self._OP_PREFIX}", "name": record.name,
                    "changes": prior})
        return record

    def remove(self, name):
        tx = self._doc._require_tx()
        name = str(name)
        record = self._records.get(name)
        if record is None:
            raise errors.StyleNotFound(self._KIND, name)
        if name == STANDARD:
            raise errors.ProtectedRecord(f"{self._KIND} style", STANDARD)
        del self._records[name]
        tx._record({"op": f"remove_{self._OP_PREFIX}", "name": name,
                    "record": record.to_dict()})
        return record

    # -- internals (journal application / rebuild; no tx) --------------------
    def _insert(self, record) -> None:
        self._records[record.name] = record

    def _drop(self, name: str):
        return self._records.pop(str(name), None)

    def _restore(self, records: list) -> None:
        names = [record.name for record in records]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate style names in {names!r}")
        self._records = {}
        if STANDARD not in names:
            self._install_standard()
        for record in records:
            self._records[record.name] = record

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.__class__.__name__} {self.names()!r}>"


class TextStyleTable(_StyleTable):
    _KIND = "text"
    _OP_PREFIX = "text_style"
    _RECORD_CLS = TextStyleRecord


class DimStyleTable(_StyleTable):
    _KIND = "dim"
    _OP_PREFIX = "dim_style"
    _RECORD_CLS = DimStyleRecord
