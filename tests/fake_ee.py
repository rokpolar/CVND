"""Recording, chainable fake of the Earth Engine client for offline tests.

Every call on the fake returns a new node that remembers the operation, its
parent and the set of "origins" (asset names / static constructors) that flowed
into it, so a test can tell an S1 image chain from an S2 one. ``getInfo`` is
answered by per-test handlers; nothing touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Call:
    target: "FakeNode | None"
    name: str
    args: tuple
    kwargs: dict = field(default_factory=dict)


def _origins_of(values) -> frozenset:
    found = set()
    for value in values:
        if isinstance(value, FakeNode):
            found |= value._origins
        elif isinstance(value, (list, tuple)):
            found |= _origins_of(value)
        elif isinstance(value, dict):
            found |= _origins_of(value.values())
    return frozenset(found)


class FakeNode:
    def __init__(self, fake, op, origins=frozenset(), parent=None, args=(), kwargs=None):
        self._fake = fake
        self._op = op
        self._origins = frozenset(origins)
        self._parent = parent
        self._args = args
        self._kwargs = kwargs or {}

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)

        def method(*args, **kwargs):
            return self._fake._call(self, name, args, kwargs)
        return method

    def __repr__(self):
        return f'FakeNode({self._op})'


class _Namespace:
    """``ee.Image`` style object: callable constructor plus static methods."""

    def __init__(self, fake, name):
        self._fake = fake
        self._name = name

    def __call__(self, *args, **kwargs):
        origins = {args[0]} if args and isinstance(args[0], str) else set()
        return self._fake._record(None, self._name, args, kwargs, origins)

    def __getattr__(self, attr):
        if attr.startswith('__'):
            raise AttributeError(attr)
        label = f'{self._name}.{attr}'

        def static(*args, **kwargs):
            return self._fake._record(None, label, args, kwargs, {label})
        return static


class FakeEE:
    NAMESPACES = ('Image', 'ImageCollection', 'FeatureCollection', 'Feature', 'Date',
                  'Filter', 'Reducer', 'Terrain', 'Geometry', 'Dictionary', 'Number',
                  'Projection', 'Algorithms', 'ErrorMargin')

    def __init__(self, reduce: Callable[[FakeNode, dict], Any] | None = None,
                 size: Callable[[FakeNode], int] | None = None,
                 orbits=('DESCENDING',), ring=None, centroid=(80.5, 20.5),
                 utm_ring=None, aggregate: Callable[[FakeNode], list] | None = None):
        self.calls: list[Call] = []
        self.reduce_handler = reduce or (lambda node, kwargs: {})
        self.size_handler = size or (lambda node: 2)
        self.aggregate_handler = aggregate or (lambda node: [])
        self.orbits = list(orbits)
        self.ring = ring or [[80.0, 20.0], [81.0, 20.0], [81.0, 21.0], [80.0, 21.0], [80.0, 20.0]]
        self.centroid = list(centroid)
        # A 3.2 km x 1.9 km box in metres: 5 x 3 tiles of 640 m.
        self.utm_ring = utm_ring or [[500003.0, 2200001.0], [503197.0, 2200001.0],
                                     [503197.0, 2201919.0], [500003.0, 2201919.0],
                                     [500003.0, 2200001.0]]
        for name in self.NAMESPACES:
            setattr(self, name, _Namespace(self, name))

    def _record(self, target, name, args, kwargs, origins=frozenset()):
        self.calls.append(Call(target, name, args, dict(kwargs)))
        base = target._origins if target is not None else frozenset()
        origins = base | frozenset(origins) | _origins_of(args) | _origins_of(kwargs.values())
        return FakeNode(self, name, origins, target, args, kwargs)

    def _call(self, node, name, args, kwargs):
        if name == 'getInfo':
            self.calls.append(Call(node, name, args, dict(kwargs)))
            return self._info(node)
        if name == 'map':
            # Exercise the mapped function on a stand-in element so its calls
            # (cloud mask, NDWI, speckle filter) are recorded too.
            element = FakeNode(self, 'element', node._origins, node)
            mapped = args[0](element)
            result = self._record(node, name, args, kwargs)
            result._origins |= getattr(mapped, '_origins', frozenset())
            return result
        return self._record(node, name, args, kwargs)

    def _info(self, node):
        op = node._op
        if op == 'size':
            return self.size_handler(node._parent)
        if op == 'reduceRegion':
            return self.reduce_handler(node._parent, node._kwargs)
        if op == 'distinct':
            return list(self.orbits)
        if op == 'coordinates':
            parent = node._parent
            if parent is not None and parent._op == 'centroid':
                return list(self.centroid)
            if parent is not None and parent._op == 'bounds' and len(parent._args) > 1:
                return [self.utm_ring]
            return [self.ring]
        if op == 'aggregate_array':
            return self.aggregate_handler(node)
        if op == 'Dictionary':
            # ee.Dictionary({...}).getInfo(): resolve each member like getInfo.
            members = node._args[0] if node._args else {}
            return {k: self._info(v) if isinstance(v, FakeNode) else v
                    for k, v in members.items()}
        if op == 'toDictionary':
            return {}
        if op == 'area':
            return 1e6
        return None

    # ── query helpers for assertions ────────────────────────────────────────
    def named(self, name):
        return [call for call in self.calls if call.name == name]

    def reduce_calls(self):
        return self.named('reduceRegion')


def reducer_kind(kwargs) -> str:
    """'Reducer.sum' etc.; ``.unweighted()`` reports its base reducer."""
    reducer = kwargs.get('reducer')
    if getattr(reducer, '_op', '') == 'unweighted':
        reducer = reducer._parent
    return getattr(reducer, '_op', '')


def is_unweighted(kwargs) -> bool:
    return getattr(kwargs.get('reducer'), '_op', '') == 'unweighted'
