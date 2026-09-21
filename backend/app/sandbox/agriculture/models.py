"""Simulated Agriculture Department sandbox: farmer, land-holding and crop-loan
records. Modeled after the Agriculture, Animal Husbandry, Dairy Development &
Fisheries Department. Entirely synthetic.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class Farmer(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "farmers"
    farmer_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    farmer_name: Mapped[str] = mapped_column(String(200))
    dob: Mapped[str] = mapped_column(String(20))
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    taluka: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class LandHolding(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "land_holdings"
    holding_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmers.farmer_id", ondelete="CASCADE"), index=True)
    survey_number: Mapped[str] = mapped_column(String(60))
    crop_type: Mapped[str] = mapped_column(String(60))
    irrigation_type: Mapped[str] = mapped_column(String(40))
    area_acres: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30))


class CropLoan(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "crop_loans"
    loan_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmers.farmer_id", ondelete="CASCADE"), index=True)
    loan_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bank_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30))


class SchemeRegistration(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "scheme_registrations"
    registration_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmers.farmer_id", ondelete="CASCADE"), index=True)
    scheme_name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("agriculture")
