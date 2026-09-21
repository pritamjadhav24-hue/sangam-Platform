"""Simulated Food, Civil Supplies & Consumer Protection Department sandbox:
ration cards and PDS entitlements. Entirely synthetic.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class RationCard(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "ration_cards"
    card_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    head_of_household_name: Mapped[str] = mapped_column(String(200))
    dob: Mapped[str] = mapped_column(String(20))
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    card_number: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    card_category: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))


class HouseholdMember(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "household_members"
    member_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("ration_cards.card_id", ondelete="CASCADE"), index=True)
    member_name: Mapped[str] = mapped_column(String(200))
    relation: Mapped[str] = mapped_column(String(40))
    dob: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)


class EntitlementRecord(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "entitlement_records"
    entitlement_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("ration_cards.card_id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(String(20))
    commodity: Mapped[str] = mapped_column(String(40))
    quantity_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("food_civil_supplies")
