"""Simulated municipal civil registration + Public Health Department sandbox:
birth certificates and immunization records. Entirely synthetic.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class ResidentIndex(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "residents_index"
    resident_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    dob: Mapped[str] = mapped_column(String(20))
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    ward: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)


class BirthCertificate(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "birth_certificates"
    certificate_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("residents_index.resident_id", ondelete="CASCADE"), index=True)
    registration_number: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    place_of_birth: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30))


class ImmunizationRecord(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "immunization_records"
    record_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("residents_index.resident_id", ondelete="CASCADE"), index=True)
    vaccine: Mapped[str] = mapped_column(String(80))
    dose_number: Mapped[int] = mapped_column(default=1)
    date_administered: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("municipal_health")
