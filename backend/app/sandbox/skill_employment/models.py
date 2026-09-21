"""Simulated Skill Development, Employment & Entrepreneurship Department
sandbox: jobseeker, skill-certification and employment-exchange records.
Entirely synthetic.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class Jobseeker(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "jobseekers"
    jobseeker_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    dateOfBirth: Mapped[str] = mapped_column(String(20))
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    qualification: Mapped[str] = mapped_column(String(80))


class SkillCertification(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "skill_certifications"
    certification_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    jobseeker_id: Mapped[str] = mapped_column(ForeignKey("jobseekers.jobseeker_id", ondelete="CASCADE"), index=True)
    trade: Mapped[str] = mapped_column(String(80))
    certification_body: Mapped[str] = mapped_column(String(120))
    issued_on: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


class EmploymentRegistration(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "employment_registrations"
    registration_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    jobseeker_id: Mapped[str] = mapped_column(ForeignKey("jobseekers.jobseeker_id", ondelete="CASCADE"), index=True)
    exchange_office: Mapped[str] = mapped_column(String(120))
    registration_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("skill_employment")
