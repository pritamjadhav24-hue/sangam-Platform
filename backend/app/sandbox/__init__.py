"""Independent, simulated Maharashtra government department data stores.

Every module under ``app.sandbox.<department>`` owns its own SQLAlchemy
``DeclarativeBase``, its own database (a separate SQLite file by default, or a
separate PostgreSQL database when ``SANDBOX_DB_URL_<DEPARTMENT>`` is set), and
its own domain-specific schema. These are simulated department-internal
systems, not SANGAM tables.

SANGAM must never import or query these modules from request-handling code
(``app.core``, ``app.engine``, ``app.api``). They exist so a future adapter
layer can call a department's own REST API (not built in this phase) the same
way a real integration would -- SANGAM does not reach into a department's
database directly, real or simulated.
"""
