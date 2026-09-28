"""Curated public-demonstration citizens.

A handful of hand-written synthetic identities, each built to show one
interoperability scenario end to end (eligible, missing data, several
documents, provider fallback, outage impact, unconfirmed identity, not
eligible). They are the only accounts the public demo sign-in offers.

The same citizen exists in several *independent* department databases, each
department keeping the record in its own way -- name order/case, address
style and phone format differ, exactly as they would between real systems.
SANGAM never copies these records; it reaches them only through each
department's API and matches them back to the citizen (entity resolution).

``departments`` describes what each department's own seed should hold for
the citizen (see ``seed_demo`` in each ``app/sandbox/<department>/seed.py``).
Everything here is synthetic demo data -- no real person is represented.
"""
from __future__ import annotations

DEMO_CITIZENS: list[dict] = [
    {
        "citizenId": "DEMO-CIT-001", "name": "Rahul Kumar", "dob": "2005-06-15", "gender": "MALE",
        "phone": "+91-9876543210", "district": "Mumbai Suburban", "address": "12 MG Road, Andheri West, Mumbai 400058",
        "persona": "STUDENT", "scenario": "ELIGIBLE", "scenarioLabel": "Eligible citizen — all records verified",
        "departments": {
            "revenue": {"name": "Rahul Kumar", "address": "12 MG Road, Andheri West, Mumbai 400058", "phone": "+91 98765 43210",
                        "income": 320000, "incomeStatus": "ISSUED", "domicile": "ISSUED"},
            "education": {"name": "RAHUL KUMAR", "phone": "9876543210", "percentage": 78.4, "academicStatus": "VERIFIED", "standard": "UG-1"},
            "social_welfare": {"name": "Kumar Rahul", "address": "12, Mahatma Gandhi Rd., Andheri(W), Mumbai", "phone": "09876543210",
                               "category": "OBC", "caste": "ISSUED", "bank": "LINKED", "verifiedIncome": 315000},
            "municipal_health": {"name": "Rahul Kumar", "birth": True},
        },
    },
    {
        "citizenId": "DEMO-CIT-002", "name": "Priya Deshmukh", "dob": "2006-02-11", "gender": "FEMALE",
        "phone": "+91-9822011223", "district": "Pune", "address": "Flat 4, Shanti Niwas, Karve Road, Kothrud, Pune 411038",
        "persona": "STUDENT", "scenario": "MISSING_INFORMATION", "scenarioLabel": "Missing information — some records not yet issued",
        "departments": {
            "revenue": {"name": "Priya Deshmukh", "address": "Flat 4, Shanti Niwas, Karve Rd, Kothrud, Pune", "phone": "9822011223",
                        "income": None, "incomeStatus": "UNDER_VERIFICATION", "domicile": "ISSUED"},
            "social_welfare": {"name": "Deshmukh Priya", "phone": "+91 98220 11223", "category": "OPEN", "bank": "LINKED"},
        },
    },
    {
        "citizenId": "DEMO-CIT-003", "name": "Sunita Jadhav", "dob": "1988-09-03", "gender": "FEMALE",
        "phone": "+91-9900112233", "district": "Nashik", "address": "22 Gangapur Road, Nashik 422013",
        "persona": "VEHICLE_OWNER", "scenario": "MULTIPLE_DOCUMENTS", "scenarioLabel": "Several department documents",
        "departments": {
            "revenue": {"name": "Sunita Jadhav", "address": "22, Gangapur Rd., Nashik", "phone": "9900112233",
                        "income": 410000, "incomeStatus": "ISSUED", "domicile": "ISSUED"},
            "social_welfare": {"name": "SUNITA JADHAV", "phone": "9900112233", "category": "SC", "caste": "ISSUED", "bank": "LINKED",
                               "verifiedIncome": 400000},
            "municipal_health": {"name": "Sunita Jadhav", "birth": True, "immunization": True},
            "transport": {"name": "Sunita S. Jadhav", "phone": "+91 99001 12233", "licence": "ACTIVE", "vehicle": "REGISTERED"},
        },
    },
    {
        "citizenId": "DEMO-CIT-004", "name": "Amit Shinde", "dob": "2004-12-20", "gender": "MALE",
        "phone": "+91-9765432109", "district": "Kolhapur", "address": "5 Rajarampuri Main Road, Kolhapur 416008",
        "persona": "STUDENT", "scenario": "FALLBACK_PROVIDER", "scenarioLabel": "Fallback provider — income also verified by Social Welfare",
        "departments": {
            "revenue": {"name": "Amit Shinde", "address": "5, Rajarampuri Main Rd, Kolhapur", "phone": "9765432109",
                        "income": 280000, "incomeStatus": "ISSUED", "domicile": "ISSUED"},
            "education": {"name": "AMIT SHINDE", "phone": "9765432109", "percentage": 72.0, "academicStatus": "VERIFIED", "standard": "UG-2"},
            "social_welfare": {"name": "Shinde Amit", "address": "5 Rajarampuri Main Road, Kolhapur", "phone": "+91 97654 32109",
                               "category": "NT-B", "caste": "ISSUED", "bank": "LINKED", "verifiedIncome": 275000},
        },
    },
    {
        "citizenId": "DEMO-CIT-005", "name": "Neha Pawar", "dob": "2005-03-28", "gender": "FEMALE",
        "phone": "+91-9812345670", "district": "Satara", "address": "Plot 9, Shahupuri, Satara 415002",
        "persona": "STUDENT", "scenario": "INCIDENT_AFFECTED", "scenarioLabel": "Affected when Revenue is unavailable (no alternative source)",
        "departments": {
            "revenue": {"name": "Neha Pawar", "address": "Plot 9, Shahupuri, Satara", "phone": "9812345670",
                        "income": 350000, "incomeStatus": "ISSUED", "domicile": "ISSUED"},
            "education": {"name": "NEHA PAWAR", "phone": "9812345670", "percentage": 81.2, "academicStatus": "VERIFIED", "standard": "UG-1"},
        },
    },
    {
        "citizenId": "DEMO-CIT-006", "name": "Sachin More", "dob": "2003-07-09", "gender": "MALE",
        "phone": "+91-9870001112", "district": "Thane", "address": "B-12 Vasant Vihar, Pokhran Road 2, Thane 400610",
        "persona": "STUDENT", "scenario": "UNCONFIRMED_IDENTITY", "scenarioLabel": "Record that cannot be confirmed as the same person",
        "departments": {
            "revenue": {"name": "Sachin More", "address": "B-12, Vasant Vihar, Pokhran Rd No. 2, Thane", "phone": "9870001112",
                        "income": 390000, "incomeStatus": "ISSUED", "domicile": "ISSUED"},
            # Same name, but a different person: other date of birth and phone.
            "education": {"name": "SACHIN MORE", "dob": "1999-01-30", "phone": "9123400000", "percentage": 66.0,
                          "academicStatus": "VERIFIED", "standard": "PG-1"},
        },
    },
    {
        "citizenId": "DEMO-CIT-007", "name": "Kiran Kale", "dob": "2005-11-02", "gender": "MALE",
        "phone": "+91-9890098900", "district": "Nagpur", "address": "44 Civil Lines, Nagpur 440001",
        "persona": "STUDENT", "scenario": "NOT_ELIGIBLE", "scenarioLabel": "Not eligible — income above the scheme limit",
        "departments": {
            "revenue": {"name": "Kiran Kale", "address": "44, Civil Lines, Nagpur", "phone": "9890098900",
                        "income": 745000, "incomeStatus": "ISSUED", "domicile": "ISSUED"},
            "education": {"name": "KIRAN KALE", "phone": "9890098900", "percentage": 88.5, "academicStatus": "VERIFIED", "standard": "UG-1"},
            "social_welfare": {"name": "Kale Kiran", "phone": "9890098900", "category": "OPEN", "bank": "LINKED"},
        },
    },
]

DEMO_CITIZENS_BY_ID = {citizen["citizenId"]: citizen for citizen in DEMO_CITIZENS}


def demo_records(department_key: str) -> list[tuple[dict, dict]]:
    """(citizen, that department's record spec) for every demo citizen the
    department holds a record for."""
    return [(citizen, citizen["departments"][department_key]) for citizen in DEMO_CITIZENS if department_key in citizen["departments"]]
