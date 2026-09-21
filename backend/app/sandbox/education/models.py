"""Simulated Education Department sandbox: student and academic records.

Modeled after School Education & Sports / Higher & Technical Education
Department record-keeping (UDISE-style school codes, academic-year results).
Entirely synthetic.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class Student(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "students"
    student_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    student_name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[str] = mapped_column(String(20))
    guardian_mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    udise_school_code: Mapped[str] = mapped_column(String(30))
    standard: Mapped[str] = mapped_column(String(20))


class AcademicRecord(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "academic_records"
    record_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.student_id", ondelete="CASCADE"), index=True)
    academic_year: Mapped[str] = mapped_column(String(20))
    percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))


class ScholarshipEligibility(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "scholarship_eligibility"
    eligibility_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.student_id", ondelete="CASCADE"), index=True)
    scheme_reference: Mapped[str] = mapped_column(String(120))
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("education")
