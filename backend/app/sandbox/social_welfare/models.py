"""Simulated Social Welfare Department sandbox: caste, bank-linkage and scheme
enrollment records. Modeled after the Social Justice & Special Assistance
Department. Entirely synthetic.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class Beneficiary(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "beneficiaries"
    beneficiary_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[str] = mapped_column(String(20))
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    social_category: Mapped[str] = mapped_column(String(30))


class CasteCertificate(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "caste_certificates"
    certificate_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    beneficiary_id: Mapped[str] = mapped_column(ForeignKey("beneficiaries.beneficiary_id", ondelete="CASCADE"), index=True)
    caste: Mapped[str] = mapped_column(String(60))
    issued_on: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


class BankLinkage(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "bank_linkages"
    linkage_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    beneficiary_id: Mapped[str] = mapped_column(ForeignKey("beneficiaries.beneficiary_id", ondelete="CASCADE"), index=True)
    bank_name: Mapped[str] = mapped_column(String(120))
    account_status: Mapped[str] = mapped_column(String(30))


class SchemeEnrollment(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "scheme_enrollments"
    enrollment_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    beneficiary_id: Mapped[str] = mapped_column(ForeignKey("beneficiaries.beneficiary_id", ondelete="CASCADE"), index=True)
    scheme_name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("social_welfare")
