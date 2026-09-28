"""Filesystem layer: locate the knowledge base and load/write its YAML records.

Everything the agent "remembers" lives in this repository. This module is the
only place that reads or writes disk; the rest of the package is pure functions
over the structures loaded here.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TRADE_ID_RE = re.compile(r"^T-(\d{4,})$")
STATUSES = ("planned", "open", "closed", "missed", "not_taken")
TAXONOMIES = ("setups", "regimes", "mistakes", "behaviors", "loss_types")
INCIDENTS_FILE = "playbook/incidents.yaml"
INCIDENT_ENUMS = {
    "area": ("tooling", "terminal", "risk", "data", "tests", "bot"),
    "severity": ("high", "medium", "low"),
    "found_by": ("agent", "test", "audit", "validator", "trader"),
    "status": ("open", "fixed", "guarded", "caught"),
}

# Defaults are ASSUMPTIONS, not facts about the trader. config.yaml overrides them.
DEFAULT_CONFIG: dict[str, Any] = {
    "breakeven_band_r": 0.10,
    "evidence_tiers": {
        "moderate_min_n": 20,
        "higher_min_n": 50,
        "higher_min_conditions": 2,
        "condition_group": "trend",
    },
    "min_n_for_ratios": 10,
    "min_n_for_ci": 5,
    "bootstrap": {"resamples": 10000, "seed": 7, "confidence": 0.95},
    "outlook": {"trades": 100, "paths": 2000},
    "recurring_error_min": 3,
    "recent_window": 20,
    "process": {"good_min": 3.5, "poor_max": 2.5, "min_scored_dimensions": 3},
    "risk_checks": {
        "stated_vs_computed_tolerance": 0.10,
        "fee_share_warn": 0.20,
        "liq_buffer_warn": 1.5,
        "default_mmr_rate": 0.005,
    },
    "promotion": {
        "change_min_evidence": {"provisional": 10, "established": 30},
        "strategy_min_trades": {"developing": 10, "established": 30},
    },
}


class KBError(Exception):
    """A knowledge-base file could not be read or parsed."""


def root() -> Path:
    env = os.environ.get("TJ_ROOT")
    return Path(env).resolve() if env else Path(__file__).resolve().parent.parent


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys. Plain YAML keeps the LAST duplicate and drops the
    first without a word: a second `inducement:` in the profile once erased the trader's first definition."""


def _mapping_without_duplicates(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    seen: dict[Any, int] = {}
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            first = seen.get(key)
        except TypeError:                     # unhashable key: construct_mapping reports it
            continue
        if first is not None:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"duplicate key {key!r} (first on line {first + 1}); YAML would silently keep only the last",
                key_node.start_mark)
        seen[key] = key_node.start_mark.line
    return loader.construct_mapping(node, deep=deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates)


def load_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.load(fh, Loader=_StrictLoader)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as exc:
        raise KBError(f"{path.name}: invalid YAML: {exc}") from exc
    except OSError as exc:
        raise KBError(f"{path}: {exc.strerror}") from exc


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def dig(data: Any, dotted: str, default: Any = None) -> Any:
    """`dig(t, "plan.stop")` -> value, or `default` if any step is missing or null."""
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def as_date(value: Any) -> dt.date | None:
    """Parse a YAML date (already a date) or ISO string. Raises ValueError if malformed."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value.strip())
    raise ValueError(f"not a date: {value!r}")


def trade_number(trade_id: Any) -> int | None:
    match = TRADE_ID_RE.match(str(trade_id))
    return int(match.group(1)) if match else None


@dataclass
class Trade:
    path: Path
    data: dict

    @property
    def id(self) -> str:
        return str(self.data.get("id"))

    @property
    def status(self) -> str | None:
        return self.data.get("status")


@dataclass
class Taxonomy:
    name: str
    tags: dict[str, dict]
    aliases: dict[str, str]
    groups: dict[str, dict]

    def resolve(self, tag: str) -> tuple[str | None, str | None]:
        """-> (canonical, None) if canonical; (None, canonical) if an alias; (None, None) if unknown."""
        if tag in self.tags:
            return tag, None
        if tag in self.aliases:
            return None, self.aliases[tag]
        return None, None


@dataclass
class Strategy:
    slug: str
    path: Path
    meta: dict
    versions: dict[str, dict]
    changes: list[dict]


@dataclass
class KB:
    root: Path
    config: dict
    profile: dict
    taxonomies: dict[str, Taxonomy]
    trades: list[Trade]
    strategies: dict[str, Strategy]
    experiments: dict[str, dict]
    load_errors: list[str] = field(default_factory=list)
    automation: dict = field(default_factory=dict)
    incidents: list = field(default_factory=list)

    def trade(self, trade_id: str) -> Trade | None:
        return next((t for t in self.trades if t.id == trade_id), None)


def _load_taxonomy(path: Path, name: str, errors: list[str]) -> Taxonomy:
    data = load_yaml(path) if path.exists() else None
    if not isinstance(data, dict) or not isinstance(data.get("tags"), dict):
        errors.append(f"taxonomy/{name}.yaml: missing or malformed `tags` mapping")
        return Taxonomy(name, {}, {}, {})
    tags = {}
    for key, meta in data["tags"].items():
        if meta is None or isinstance(meta, dict):
            tags[str(key)] = meta or {}
        else:
            tags[str(key)] = {"label": str(meta)}
    aliases: dict[str, str] = {}
    for tag, meta in tags.items():
        for alias in meta.get("aliases") or []:
            aliases[str(alias)] = tag
    groups = data.get("groups") or {}
    return Taxonomy(name, tags, aliases, groups)


def _load_trades(r: Path, errors: list[str]) -> list[Trade]:
    trades: list[Trade] = []
    for path in (r / "journal" / "trades").glob("*.yaml"):
        try:
            data = load_yaml(path)
        except KBError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(data, dict):
            errors.append(f"{path.name}: expected a mapping at top level")
            continue
        trades.append(Trade(path, data))
    trades.sort(key=lambda t: (trade_number(t.id) is None, trade_number(t.id) or 0, t.path.name))
    return trades


def _load_strategies(r: Path, errors: list[str]) -> dict[str, Strategy]:
    out: dict[str, Strategy] = {}
    base = r / "playbook" / "strategies"
    if not base.exists():
        return out
    for sdir in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        try:
            meta = load_yaml(sdir / "strategy.yaml") if (sdir / "strategy.yaml").exists() else None
            versions = {}
            for vpath in sorted(sdir.glob("v*.yaml")):
                versions[vpath.stem[1:]] = load_yaml(vpath) or {}
            changes_doc = load_yaml(sdir / "changes.yaml") if (sdir / "changes.yaml").exists() else {}
        except KBError as exc:
            errors.append(f"strategies/{sdir.name}: {exc}")
            continue
        if not isinstance(meta, dict):
            errors.append(f"strategies/{sdir.name}: missing or malformed strategy.yaml")
            continue
        changes = (changes_doc or {}).get("changes") or []
        out[sdir.name] = Strategy(sdir.name, sdir, meta, versions, changes)
    return out


def _load_experiments(r: Path, errors: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    base = r / "playbook" / "experiments"
    if not base.exists():
        return out
    for path in sorted(base.glob("*.yaml")):
        try:
            data = load_yaml(path)
        except KBError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(data, dict):
            errors.append(f"experiments/{path.name}: expected a mapping")
            continue
        data["_file"] = path.stem
        out[str(data.get("id", path.stem))] = data
    return out


def load_kb(r: Path | None = None) -> KB:
    r = r or root()
    errors: list[str] = []
    config = copy.deepcopy(DEFAULT_CONFIG)
    try:
        user_config = load_yaml(r / "config.yaml") if (r / "config.yaml").exists() else {}
        if isinstance(user_config, dict):
            config = deep_merge(DEFAULT_CONFIG, user_config)
        elif user_config is not None:
            errors.append("config.yaml: expected a mapping; using defaults")
    except KBError as exc:
        errors.append(str(exc))
    try:
        profile = load_yaml(r / "profile" / "trader.yaml") or {}
    except KBError as exc:
        errors.append(str(exc))
        profile = {}
    taxonomies = {}
    for name in TAXONOMIES:
        try:
            taxonomies[name] = _load_taxonomy(r / "taxonomy" / f"{name}.yaml", name, errors)
        except KBError as exc:
            errors.append(str(exc))
            taxonomies[name] = Taxonomy(name, {}, {}, {})
    automation: dict = {}
    if (r / "playbook" / "automation.yaml").exists():
        try:
            loaded = load_yaml(r / "playbook" / "automation.yaml")
            if isinstance(loaded, dict):
                automation = loaded
            else:
                errors.append("playbook/automation.yaml: expected a mapping")
        except KBError as exc:
            errors.append(str(exc))
    incidents: list = []
    if (r / INCIDENTS_FILE).exists():
        try:
            loaded = load_yaml(r / INCIDENTS_FILE) or {}
            if isinstance(loaded, dict) and isinstance(loaded.get("incidents") or [], list):
                incidents = loaded.get("incidents") or []
            else:
                errors.append(f"{INCIDENTS_FILE}: expected a mapping with an `incidents` list")
        except KBError as exc:
            errors.append(str(exc))
    return KB(
        root=r,
        config=config,
        profile=profile if isinstance(profile, dict) else {},
        taxonomies=taxonomies,
        trades=_load_trades(r, errors),
        strategies=_load_strategies(r, errors),
        experiments=_load_experiments(r, errors),
        load_errors=errors,
        automation=automation,
        incidents=incidents,
    )


def unresolved(mapping: Any, prefix: str = "") -> list[str]:
    """Dotted paths of every null leaf: parameters the agent must learn, never invent."""
    out: list[str] = []
    if isinstance(mapping, dict):
        for key, value in mapping.items():
            path = f"{prefix}{key}"
            if value is None:
                out.append(path)
            elif isinstance(value, dict):
                out.extend(unresolved(value, path + "."))
    return out


def next_trade_id(trades: list[Trade]) -> str:
    numbers = [n for n in (trade_number(t.id) for t in trades) if n is not None]
    return f"T-{(max(numbers) + 1 if numbers else 1):04d}"


def _scalar(value: str | None) -> str:
    return "null" if value is None else json.dumps(value)


def create_trade(kb: KB, *, status: str, opened: dt.date, asset: str | None = None,
                 direction: str | None = None, market: str | None = None) -> Path:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if direction not in (None, "long", "short"):
        raise ValueError("direction must be long or short")
    template = (kb.root / "templates" / "trade.yaml").read_text(encoding="utf-8")
    trade_id = next_trade_id(kb.trades)
    text = (template
            .replace("__ID__", trade_id)
            .replace("__STATUS__", status)
            .replace("__OPENED__", opened.isoformat())
            .replace("__ASSET__", _scalar(asset))
            .replace("__DIRECTION__", _scalar(direction))
            .replace("__MARKET__", _scalar(market)))
    path = kb.root / "journal" / "trades" / f"{trade_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:
        fh.write(text)
    return path
