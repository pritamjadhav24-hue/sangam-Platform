"""Simulated Labour Department sandbox: registered worker, establishment and
welfare-board-membership records. Modeled after the Labour Department incl.
the Maharashtra Building & Other Construction Workers Welfare Board.
Entirely synthetic.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.sandbox.common import SyntheticFlagMixin, TimestampMixin, build_document_table, make_engine


class Base(DeclarativeBase):
    pass


class RegisteredWorker(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "registered_workers"
    worker_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    citizen_ref: Mapped[str] = mapped_column(String(120), index=True)
    worker_name: Mapped[str] = mapped_column(String(200))
    dateOfBirth: Mapped[str] = mapped_column(String(20))
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    occupation: Mapped[str] = mapped_column(String(80))


class EstablishmentRegistration(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "establishment_registrations"
    establishment_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("registered_workers.worker_id", ondelete="CASCADE"), index=True)
    establishment_name: Mapped[str] = mapped_column(String(160))
    registration_number: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


class WelfareBoardMembership(Base, TimestampMixin, SyntheticFlagMixin):
    __tablename__ = "welfare_board_memberships"
    membership_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("registered_workers.worker_id", ondelete="CASCADE"), index=True)
    board_name: Mapped[str] = mapped_column(String(160), default="Maharashtra Building & Other Construction Workers Welfare Board")
    membership_number: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(30))


SyntheticDocument = build_document_table(Base)

ENGINE = make_engine("labour")
