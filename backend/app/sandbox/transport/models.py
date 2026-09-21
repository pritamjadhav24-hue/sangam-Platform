"""Simulated Transport Department (RTO) sandbox: vehicle registrations and
driving licences. Modeled after the Maharashtra Transport Commissionerate.
Entirely synthetic.
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
    rto_office: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class VehicleRegistration(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "vehicle_registrations"
    registration_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("residents_index.resident_id", ondelete="CASCADE"), index=True)
    vehicle_number: Mapped[str] = mapped_column(String(30))
    vehicle_class: Mapped[str] = mapped_column(String(40))
    registration_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


class DrivingLicence(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "driving_licences"
    licence_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("residents_index.resident_id", ondelete="CASCADE"), index=True)
    licence_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    licence_class: Mapped[str] = mapped_column(String(40))
    valid_until: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("transport")
