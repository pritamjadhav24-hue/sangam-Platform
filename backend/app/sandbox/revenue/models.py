"""Simulated Revenue Department sandbox: land, domicile and income records.

Modeled after the Maharashtra Revenue & Forests Department's Tehsildar-level
record keeping (7/12 extracts, domicile and income certificates). Entirely
synthetic -- not connected to any real land/revenue system.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class ResidentIndex(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "resident_index"
    resident_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    dob: Mapped[str] = mapped_column(String(20))
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    taluka: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    village: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_line: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)


class LandRecord(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "land_records"
    record_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("resident_index.resident_id", ondelete="CASCADE"), index=True)
    survey_number: Mapped[str] = mapped_column(String(60))
    khata_number: Mapped[str] = mapped_column(String(60))
    area_hectares: Mapped[float] = mapped_column(Float)
    land_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))


class DomicileCertificate(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "domicile_certificates"
    certificate_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("resident_index.resident_id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(60), default="Maharashtra")
    issued_on: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    valid_until: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


class IncomeCertificate(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "income_certificates"
    certificate_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("resident_index.resident_id", ondelete="CASCADE"), index=True)
    annual_income: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    financial_year: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("revenue")
