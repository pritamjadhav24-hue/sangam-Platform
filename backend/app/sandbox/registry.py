"""Manifest of simulated Maharashtra government department sandboxes.

Adding a new department to the platform is meant to be mostly a matter of
adding one module pair (``models.py`` + ``seed.py``) and one entry here, not a
change to shared plumbing. ``real_department`` documents which real
Maharashtra government department/directorate the simulated domain is modeled
after -- these are still entirely synthetic sandboxes, never a live
integration.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxSpec:
    key: str
    label: str
    real_department: str
    models_module: str
    seed_module: str


SANDBOXES: list[SandboxSpec] = [
    SandboxSpec("revenue", "Revenue Sandbox", "Revenue & Forests Department (Maharashtra)",
                "app.sandbox.revenue.models", "app.sandbox.revenue.seed"),
    SandboxSpec("education", "Education Sandbox", "School Education & Sports Department / Higher & Technical Education Department",
                "app.sandbox.education.models", "app.sandbox.education.seed"),
    SandboxSpec("social_welfare", "Social Welfare Sandbox", "Social Justice & Special Assistance Department",
                "app.sandbox.social_welfare.models", "app.sandbox.social_welfare.seed"),
    SandboxSpec("agriculture", "Agriculture Sandbox", "Agriculture, Animal Husbandry, Dairy Development & Fisheries Department",
                "app.sandbox.agriculture.models", "app.sandbox.agriculture.seed"),
    SandboxSpec("transport", "Transport Sandbox", "Home Department -- Transport Commissionerate (RTO)",
                "app.sandbox.transport.models", "app.sandbox.transport.seed"),
    SandboxSpec("labour", "Labour Sandbox", "Labour Department (incl. Maharashtra Building & Other Construction Workers Welfare Board)",
                "app.sandbox.labour.models", "app.sandbox.labour.seed"),
    SandboxSpec("food_civil_supplies", "Food & Civil Supplies Sandbox", "Food, Civil Supplies & Consumer Protection Department",
                "app.sandbox.food_civil_supplies.models", "app.sandbox.food_civil_supplies.seed"),
    SandboxSpec("housing", "Housing Sandbox", "Housing Department (MHADA-style public housing schemes)",
                "app.sandbox.housing.models", "app.sandbox.housing.seed"),
    SandboxSpec("skill_employment", "Skill Development & Employment Sandbox", "Skill Development, Employment & Entrepreneurship Department",
                "app.sandbox.skill_employment.models", "app.sandbox.skill_employment.seed"),
    SandboxSpec("municipal_health", "Municipal Health Sandbox", "Urban local body civil registration + Public Health Department",
                "app.sandbox.municipal_health.models", "app.sandbox.municipal_health.seed"),
]

SANDBOXES_BY_KEY = {spec.key: spec for spec in SANDBOXES}
