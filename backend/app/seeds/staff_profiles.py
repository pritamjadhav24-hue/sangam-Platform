"""Office details shown on staff profile pages.

Deliberately non-sensitive placeholder values (reserved ``.example`` email
domain, fictional 555 numbers): the platform keeps no personal records for
staff accounts. Nothing here is a credential.
"""
STAFF_PROFILES = {
    "ADMIN_MH_01": {
        "designation": "Platform Administrator",
        "organisation": "SANGAM Operations",
        "unit": "State Services Integration Cell",
        "officialEmail": "platform.admin@sangam.example",
        "phone": "+91 22 5550 0101",
        "accessLevel": "Full operational access",
        "accountCreated": "2026-01-15",
    },
    "OFFICER_MH_01": {
        "designation": "Scheme Verification Officer",
        "organisation": "SANGAM Operations",
        "unit": "Application Review Desk",
        "officialEmail": "review.officer@sangam.example",
        "phone": "+91 22 5550 0102",
        "accessLevel": "Application review",
        "accountCreated": "2026-01-15",
    },
}
