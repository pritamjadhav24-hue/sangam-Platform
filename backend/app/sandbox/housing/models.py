"""Simulated Housing Department sandbox: public housing scheme applications
and allotments (MHADA-style). Entirely synthetic.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class Applicant(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "applicants"
    applicant_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    applicant_name: Mapped[str] = mapped_column(String(200))
    dob: Mapped[str] = mapped_column(String(20))
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    income_category: Mapped[str] = mapped_column(String(20))


class HousingApplication(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "housing_applications"
    application_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    applicant_id: Mapped[str] = mapped_column(ForeignKey("applicants.applicant_id", ondelete="CASCADE"), index=True)
    scheme_name: Mapped[str] = mapped_column(String(160))
    application_date: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))


class Allotment(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "allotments"
    allotment_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("housing_applications.application_id", ondelete="CASCADE"), index=True)
    project_name: Mapped[str] = mapped_column(String(160))
    unit_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    allotment_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("housing")
