"""CLI for creating, seeding, resetting and inspecting department sandboxes.

Usage (from the backend/ directory):

    python -m app.sandbox.manage create-all
    python -m app.sandbox.manage seed-all
    python -m app.sandbox.manage reset-all
    python -m app.sandbox.manage status

Each department sandbox is its own database (SQLite file by default; see
``app.sandbox.common.sandbox_db_url``). This script never touches SANGAM's own
PostgreSQL database.
"""
from __future__ import annotations

import argparse
import importlib
import sys

from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES, SANDBOXES_BY_KEY
from app.seeds.synthetic_identity_pool import generate_citizen_pool


def _load(spec):
    models = importlib.import_module(spec.models_module)
    seed = importlib.import_module(spec.seed_module)
    return models, seed


def create_all(keys: list[str] | None = None) -> None:
    for spec in _selected(keys):
        models, _ = _load(spec)
        models.Base.metadata.create_all(models.ENGINE)
        print(f"[create] {spec.key}: tables ready ({spec.label})")


def reset_all(keys: list[str] | None = None) -> None:
    for spec in _selected(keys):
        models, _ = _load(spec)
        models.Base.metadata.drop_all(models.ENGINE)
        models.Base.metadata.create_all(models.ENGINE)
        print(f"[reset] {spec.key}: tables recreated ({spec.label})")


def seed_all(keys: list[str] | None = None, citizen_count: int = 60) -> None:
    citizens = generate_citizen_pool(citizen_count)
    for spec in _selected(keys):
        models, seed = _load(spec)
        models.Base.metadata.create_all(models.ENGINE)
        with session_scope(models.ENGINE) as session:
            result = seed.seed(session, citizens)
        print(f"[seed] {spec.key}: {result}")


def status(keys: list[str] | None = None) -> None:
    for spec in _selected(keys):
        models, _ = _load(spec)
        tables = models.Base.metadata.tables
        with session_scope(models.ENGINE) as session:
            counts = {name: _count(session, table) for name, table in tables.items()}
        print(f"[status] {spec.key} ({spec.label}): {counts}")


def _count(session, table) -> int:
    from sqlalchemy import func, select
    return session.execute(select(func.count()).select_from(table)).scalar_one()


def _selected(keys: list[str] | None):
    if not keys:
        return SANDBOXES
    missing = [key for key in keys if key not in SANDBOXES_BY_KEY]
    if missing:
        raise SystemExit(f"Unknown department sandbox key(s): {', '.join(missing)}")
    return [SANDBOXES_BY_KEY[key] for key in keys]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage simulated Maharashtra government department sandboxes.")
    parser.add_argument("command", choices=["create-all", "seed-all", "reset-all", "status"])
    parser.add_argument("--department", action="append", dest="departments", help="Limit to one department key (repeatable). Default: all.")
    parser.add_argument("--citizens", type=int, default=60, help="Synthetic citizen pool size for seed-all (default 60).")
    args = parser.parse_args(argv)

    if args.command == "create-all":
        create_all(args.departments)
    elif args.command == "seed-all":
        seed_all(args.departments, args.citizens)
    elif args.command == "reset-all":
        reset_all(args.departments)
    elif args.command == "status":
        status(args.departments)
    return 0


if __name__ == "__main__":
    sys.exit(main())
