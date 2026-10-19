"""Layer table (contract: m2-module-contracts.md §2.2; M1 §3.2 amended).

The M1 names-only layer list becomes an ordered table of
:class:`LayerRecord` objects. "0" is always present and always first;
the record set is document content — every mutation happens inside an
open transaction and journals the ops ``add_layer`` / ``remove_layer`` /
``mutate_layer`` (v2 payloads; M1 bare ``add_layer``/``remove_layer``
journal ops replay tolerantly with default records).

Guards (binding):

- ``remove("0")`` is refused — the always-present record
  (:class:`errors.ProtectedRecord`);
- ``remove`` refuses layers that still carry entities
  (:class:`errors.LayerNotEmpty`).

Semantics of the record flags (ON/FROZEN/LOCKED) are enforced at
consumers (commands/sync/osnap — contract §2.2), not here: bcdoc stores
the state, it does not police pick behavior.

Compat surface kept for M1 callers (bcio/bcagent): ``name in
doc.layers``, ``len(doc.layers)``, iteration over names,
``doc.layers == ["0", ...]`` (name-sequence equality against lists), and
``Document.add_layer(name)`` as a thin wrapper creating a default record.
"""

from __future__ import annotations

from . import errors

#: Mutable property fields of a layer record, in serialization order
#: (contracts §2.2 / §2.7: name first, then these in this order).
LAYER_PROPS = ("color", "linetype", "lineweight", "on", "frozen", "locked", "plot")

#: Record key order for serialization (pinned, byte-stability contract).
_RECORD_KEYS = ("name",) + LAYER_PROPS


class LayerRecord:
    """One layer: name + display properties + state flags (contract §2.2)."""

    def __init__(self, name, color=7, linetype="Continuous", lineweight=None,
                 on=True, frozen=False, locked=False, plot=True):
        self.name = str(name)
        self.color = self._coerce("color", color)
        self.linetype = self._coerce("linetype", linetype)
        self.lineweight = self._coerce("lineweight", lineweight)
        self.on = self._coerce("on", on)
        self.frozen = self._coerce("frozen", frozen)
        self.locked = self._coerce("locked", locked)
        self.plot = self._coerce("plot", plot)

    # -- validation ------------------------------------------------------
    @staticmethod
    def _coerce(prop: str, value):
        if prop == "color":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"layer color must be an int (ACI), got {value!r}")
            if value < 0:
                raise ValueError(f"layer color must be >= 0, got {value!r}")
            return value
        if prop == "linetype":
            if not isinstance(value, str):
                raise ValueError(f"layer linetype must be a string, got {value!r}")
            return value
        if prop == "lineweight":
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"layer lineweight must be None or a number, got {value!r}")
            weight = float(value)
            if weight < 0:
                raise ValueError(f"layer lineweight must be >= 0, got {value!r}")
            return weight
        # on / frozen / locked / plot
        if not isinstance(value, bool):
            raise ValueError(f"layer {prop} must be a bool, got {value!r}")
        return value

    def set(self, **changes) -> dict:
        """Validate + apply property changes; return the PRIOR values
        (no partial apply — everything is validated first)."""
        for key in changes:
            if key not in LAYER_PROPS:
                raise ValueError(f"unknown layer property {key!r}")
        coerced = {k: self._coerce(k, v) for k, v in changes.items()}
        prior = {k: getattr(self, k) for k in changes}
        for key, value in coerced.items():
            setattr(self, key, value)
        return prior

    # -- serialization ----------------------------------------------------
    def to_dict(self) -> dict:
        """Fixed-order record dict {name, color, linetype, lineweight, on,
        frozen, locked, plot} (pinned key order, contract §2.7)."""
        return {key: getattr(self, key) for key in _RECORD_KEYS}

    def props_dict(self) -> dict:
        """The property subset (without the name) — the journal ``props``
        payload of ``add_layer`` ops."""
        return {key: getattr(self, key) for key in LAYER_PROPS}

    @classmethod
    def from_dict(cls, data: dict) -> "LayerRecord":
        """Tolerant rebuild (missing property keys -> defaults; used by
        journal replay and deserialization)."""
        if not isinstance(data, dict) or "name" not in data:
            raise ValueError(f"layer record must be a dict with a 'name', got {data!r}")
        kwargs = {key: data[key] for key in LAYER_PROPS if key in data}
        return cls(data["name"], **kwargs)

    def copy(self) -> "LayerRecord":
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        return clone

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<LayerRecord {self.name!r} color={self.color} "
                f"linetype={self.linetype!r} lineweight={self.lineweight} "
                f"on={self.on} frozen={self.frozen} locked={self.locked} "
                f"plot={self.plot}>")


class LayerTable:
    """Ordered layer table: "0" first and always present (contract §2.2).

    Mutating methods require the owning document's open transaction and
    journal their ops; read methods are always legal.
    """

    def __init__(self, document=None):
        self._doc = document
        # "0" always present, always first.
        self._records: list = [LayerRecord("0")]

    # -- reads -------------------------------------------------------------
    def names(self) -> list:
        """Layer names in table order ("0" first)."""
        return [record.name for record in self._records]

    def get(self, name: str):
        """The record for ``name`` or None."""
        name = str(name)
        for record in self._records:
            if record.name == name:
                return record
        return None

    def records(self) -> list:
        """Ordered copies of all records (read-only snapshot)."""
        return [record.copy() for record in self._records]

    def __contains__(self, name) -> bool:
        try:
            return self.get(name) is not None
        except Exception:
            return False

    def __iter__(self):
        return iter(self.names())

    def __len__(self) -> int:
        return len(self._records)

    def __eq__(self, other) -> bool:
        """Name-sequence equality against lists/tuples (M1 call-site compat:
        ``doc.layers == ["0", "WALLS"]`` keeps working)."""
        if isinstance(other, LayerTable):
            return self.names() == other.names()
        if isinstance(other, (list, tuple)):
            return self.names() == list(other)
        return NotImplemented

    def __ne__(self, other) -> bool:
        result = self.__eq__(other)
        return not result if result is not NotImplemented else NotImplemented

    __hash__ = None  # mutable table; identity semantics only

    # -- mutations (transaction + journal required) --------------------------
    def add(self, name, **props) -> LayerRecord:
        tx = self._doc._require_tx()
        name = str(name)
        if self.get(name) is not None:
            raise errors.DuplicateLayer(name)
        for key in props:
            if key not in LAYER_PROPS:
                raise ValueError(f"unknown layer property {key!r}")
        record = LayerRecord(name, **props)  # ValueError on bad props
        self._records.append(record)
        tx._record({"op": "add_layer", "name": name,
                    "props": record.props_dict()})
        return record

    def set_props(self, name, **changes) -> LayerRecord:
        tx = self._doc._require_tx()
        record = self.get(name)
        if record is None:
            raise errors.LayerNotFound(name)
        prior = record.set(**changes)  # validates everything first
        tx._record({"op": "mutate_layer", "name": record.name,
                    "changes": prior})
        return record

    def remove(self, name) -> LayerRecord:
        tx = self._doc._require_tx()
        record = self.get(name)
        if record is None:
            raise errors.LayerNotFound(name)
        if record.name == "0":
            raise errors.ProtectedRecord("layer", "0")
        carriers = self._doc._entities_on_layer(record.name)
        if carriers:
            raise errors.LayerNotEmpty(record.name, len(carriers))
        self._records.remove(record)
        tx._record({"op": "remove_layer", "name": record.name,
                    "record": record.to_dict()})
        return record

    # -- internals (journal application / rebuild; no tx) --------------------
    def _append(self, record: LayerRecord) -> None:
        """Insert an already-built record (journal replay / load)."""
        if record.name == "0":
            # keep "0" first and singular
            self._records[:] = [r for r in self._records if r.name != "0"]
            self._records.insert(0, record)
        else:
            self._records.append(record)

    def _drop(self, name: str):
        record = self.get(name)
        if record is not None:
            self._records.remove(record)
        return record

    def _restore(self, records: list) -> None:
        """Adopt a full record list (transaction rollback / load); "0" is
        moved to the front if a caller-supplied list has it elsewhere."""
        names = [record.name for record in records]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate layer names in {names!r}")
        if "0" not in names:
            records = [LayerRecord("0")] + list(records)
        else:
            zero = [r for r in records if r.name == "0"]
            rest = [r for r in records if r.name != "0"]
            records = zero + rest
        self._records = list(records)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LayerTable {self.names()!r}>"
