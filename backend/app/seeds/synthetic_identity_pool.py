"""Canonical synthetic citizen identity pool.

This is the single generator of "platform citizens" used both to seed SANGAM's
own ``citizens`` table and to feed every independent department sandbox seed
script (``app/sandbox/<department>/seed.py``). Using one generator is what lets
the *same* synthetic citizen_id appear, with department-appropriate field
variations, across several isolated department databases -- demonstrating
cross-department entity resolution without SANGAM ever copying department data.

Everything here is deterministic (a fixed RNG seed) so seeding is repeatable.
All records are explicitly synthetic/demo data; no real citizen or government
data is used or referenced.
"""
from __future__ import annotations

import random

SYNTHETIC_SEED = 20260921

MAHARASHTRA_DISTRICTS = [
    "Mumbai City", "Mumbai Suburban", "Pune", "Nagpur", "Nashik", "Thane",
    "Aurangabad", "Solapur", "Kolhapur", "Amravati", "Nanded", "Sangli",
    "Satara", "Akola", "Latur", "Ahmednagar", "Chandrapur", "Jalgaon",
    "Ratnagiri", "Wardha",
]

FIRST_NAMES_MALE = [
    "Rahul", "Amit", "Suresh", "Ganesh", "Vijay", "Sandeep", "Pravin", "Mahesh",
    "Ramesh", "Anil", "Sachin", "Vikram", "Rohit", "Ashok", "Sanjay", "Kiran",
    "Santosh", "Nilesh", "Dattatray", "Balaji", "Yogesh", "Prakash", "Rajesh", "Tushar",
]
FIRST_NAMES_FEMALE = [
    "Asha", "Sunita", "Priya", "Kavita", "Pooja", "Snehal", "Manisha", "Rekha",
    "Shalini", "Anjali", "Nikita", "Swati", "Vaishali", "Madhuri", "Jyoti", "Sarita",
    "Komal", "Rutuja", "Neha", "Sushma", "Shraddha", "Pallavi", "Meenal", "Archana",
]
LAST_NAMES = [
    "Patil", "Kumar", "Deshmukh", "Jadhav", "Shinde", "Pawar", "Kale", "More",
    "Chavan", "Kulkarni", "Bhosale", "Gaikwad", "Joshi", "Sable", "Rane", "Kadam",
    "Thorat", "Wagh", "Gawde", "Salunkhe", "Mane", "Waghmare", "Bhoir", "Kamble",
]

PERSONAS = [
    "STUDENT", "FARMER", "INDUSTRIAL_WORKER", "JOBSEEKER", "SENIOR_CITIZEN",
    "BUSINESS_OWNER", "VEHICLE_OWNER", "BPL_HOUSEHOLD", "NEW_PARENT", "GENERAL",
]

# Roughly which personas make sense at which age bracket, so generated data
# stays internally plausible (a 8-year-old is never a FARMER or VEHICLE_OWNER).
_ADULT_ONLY_PERSONAS = {"FARMER", "INDUSTRIAL_WORKER", "JOBSEEKER", "BUSINESS_OWNER", "VEHICLE_OWNER", "NEW_PARENT"}
_SENIOR_PERSONA = "SENIOR_CITIZEN"
_STUDENT_PERSONA = "STUDENT"


def _random_dob(rng: random.Random, min_age: int, max_age: int) -> str:
    import datetime
    today = datetime.date(2026, 9, 21)
    age_days = rng.randint(min_age * 365, max_age * 365)
    dob = today - datetime.timedelta(days=age_days)
    return dob.isoformat()


def _phone(rng: random.Random) -> str:
    return f"+91-9{rng.randint(100000000, 999999999)}"


def name_parts(full_name: str) -> dict:
    """Split a generated 'First Last' name into department-friendly parts."""
    pieces = full_name.split(" ")
    first = pieces[0]
    last = pieces[-1] if len(pieces) > 1 else ""
    return {"firstName": first, "lastName": last}


def spelling_variant(rng: random.Random, name: str) -> str:
    """Produce a controlled near-miss spelling of a name.

    Used to seed a minority of department records with realistic transcription
    drift, so entity resolution's fuzzy name matching has real MEDIUM-confidence
    cases to resolve instead of only exact matches.
    """
    if len(name) < 4:
        return name
    swaps = {"ee": "i", "ii": "i", "sh": "s", "v": "w", "ph": "f"}
    for source, target in swaps.items():
        if source in name.lower():
            index = name.lower().index(source)
            return name[:index] + target + name[index + len(source):]
    # Fall back to dropping one interior character.
    mid = len(name) // 2
    return name[:mid] + name[mid + 1:]


def generate_citizen_pool(count: int = 60) -> list[dict]:
    """Return ``count`` deterministic synthetic citizens.

    Each citizen carries one or more ``personas`` (life-situation tags) that
    department sandbox seed scripts use to decide which of them should have
    records in that department -- e.g. only ``FARMER`` personas get rows in the
    Agriculture sandbox, only ``STUDENT`` personas get rows in Education.
    """
    rng = random.Random(SYNTHETIC_SEED)
    citizens = []
    for index in range(1, count + 1):
        citizen_id = f"SYN-CIT-{index:05d}"
        gender = "FEMALE" if rng.random() < 0.5 else "MALE"
        first_pool = FIRST_NAMES_FEMALE if gender == "FEMALE" else FIRST_NAMES_MALE
        full_name = f"{rng.choice(first_pool)} {rng.choice(LAST_NAMES)}"

        persona_count = rng.choices([1, 2, 3], weights=[0.5, 0.35, 0.15])[0]
        persona_pool = list(PERSONAS)
        rng.shuffle(persona_pool)
        personas = persona_pool[:persona_count]

        if _STUDENT_PERSONA in personas:
            dob = _random_dob(rng, 6, 24)
        elif _SENIOR_PERSONA in personas:
            dob = _random_dob(rng, 60, 85)
        elif any(persona in _ADULT_ONLY_PERSONAS for persona in personas):
            dob = _random_dob(rng, 22, 58)
        else:
            dob = _random_dob(rng, 5, 70)

        citizens.append({
            "citizenId": citizen_id,
            "name": full_name,
            "dob": dob,
            "gender": gender,
            "phone": _phone(rng),
            "district": rng.choice(MAHARASHTRA_DISTRICTS),
            "personas": personas,
            "persona": personas[0],
            "synthetic": True,
        })
    return citizens


def citizens_with_persona(pool: list[dict], persona: str) -> list[dict]:
    return [citizen for citizen in pool if persona in citizen.get("personas", [])]
