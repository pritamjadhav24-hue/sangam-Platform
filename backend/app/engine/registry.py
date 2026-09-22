from __future__ import annotations

import os


class CatalogConfigurationError(RuntimeError):
    """The authoritative catalog could not be read or is incomplete."""


def _demo_fallback_enabled() -> bool:
    return os.getenv("SANGAM_ENV", "development").strip().lower() not in {"production", "prod"} and os.getenv("SANGAM_ALLOW_DEMO_FALLBACK", "false").lower() in {"1", "true", "yes"}

SCHEMES = [{
    "id": "SCH-MH-2026", "name": "Post-Matric Higher Education Scholarship",
    "nameMr": "माध्यमिकोत्तर उच्च शिक्षण शिष्यवृत्ती", "department": "Higher Education Department",
    "departmentMr": "उच्च शिक्षण विभाग", "category": "Education",
    "description": "Financial assistance for eligible students pursuing higher education after Class 10, verified automatically across income, caste, domicile and academic records.",
    "benefits": "Tuition and maintenance allowance for the academic year, disbursed directly to the student's linked bank account.",
    "eligibility": "Maharashtra domicile students enrolled in a recognised post-matric course, subject to family income and category criteria.",
    "applicationWindow": "Applications open for the current academic year.",
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "INCOME_PROOF", "label": "Income proof", "mandatory": True},
        {"code": "CASTE_PROOF", "label": "Caste proof", "mandatory": True},
        {"code": "DOMICILE_PROOF", "label": "Maharashtra domicile", "mandatory": True},
        {"code": "ACADEMIC_RECORD", "label": "Academic record", "mandatory": True},
        {"code": "BANK_DETAILS", "label": "DBT bank status", "mandatory": True},
    ],
}, {
    "id": "EDU-ACADEMIC-2026", "name": "Academic Record Verification",
    "nameMr": "शैक्षणिक नोंद पडताळणी", "department": "Education Department",
    "departmentMr": "शिक्षण विभाग", "category": "Education",
    "description": "Standalone verification of a student's academic record directly against the Education Department, without a scholarship application.",
    "benefits": "A verified academic record reference usable wherever proof of enrolment or marks is required.",
    "eligibility": "Any citizen with a recorded academic history in the Education Department.",
    "applicationWindow": "Available year-round.",
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "ACADEMIC_RECORD", "label": "Academic record", "mandatory": True},
    ],
}, {
    "id": "AGR-INPUT-SUBSIDY-2026", "name": "Farmer Input Subsidy Assistance",
    "nameMr": "शेतकरी निविष्ठा अनुदान सहाय्य", "department": "Agriculture, Animal Husbandry, Dairy Development & Fisheries Department",
    "departmentMr": "कृषी, पशुसंवर्धन, दुग्धव्यवसाय विकास व मत्स्यव्यवसाय विभाग", "category": "Agriculture",
    "description": "Support for registered farmers to access subsidised seeds, fertilizers and other farm inputs through their verified land-holding and farmer registration records.",
    "benefits": "Subsidy support applied toward eligible farm input purchases for the sown season.",
    "eligibility": "Farmers registered with the Agriculture Department with an active land-holding record.",
    "applicationWindow": "Applications open ahead of each sowing season.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "FARMER_REGISTRATION", "label": "Farmer registration", "mandatory": True},
    ],
}, {
    "id": "TRN-VEHICLE-VERIFY-2026", "name": "Vehicle Registration Verification Service",
    "nameMr": "वाहन नोंदणी पडताळणी सेवा", "department": "Home Department -- Transport Commissionerate (RTO)",
    "departmentMr": "परिवहन आयुक्तालय (आरटीओ)", "category": "Transport",
    "description": "On-demand verification of a citizen's vehicle registration record with the Regional Transport Office, for use wherever proof of registration is required.",
    "benefits": "A verified vehicle registration reference confirming current registration status.",
    "eligibility": "Any citizen with a vehicle registered with the Transport Department.",
    "applicationWindow": "Available year-round.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "VEHICLE_REGISTRATION", "label": "Vehicle registration", "mandatory": True},
    ],
}, {
    "id": "FCS-RATION-CARD-2026", "name": "Ration Card Issuance Assistance",
    "nameMr": "शिधापत्रिका जारी सहाय्य", "department": "Food, Civil Supplies & Consumer Protection Department",
    "departmentMr": "अन्न, नागरी पुरवठा व ग्राहक संरक्षण विभाग", "category": "Food & Public Distribution",
    "description": "Assistance verifying and linking an existing ration card record for access to public distribution system entitlements.",
    "benefits": "Verified ration card status enabling continued access to subsidised food-grain entitlements.",
    "eligibility": "Households already holding, or eligible to hold, a ration card issued by the department.",
    "applicationWindow": "Available year-round.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "RATION_CARD", "label": "Ration card", "mandatory": True},
    ],
}, {
    "id": "HSG-ALLOTMENT-2026", "name": "Public Housing Allotment Scheme",
    "nameMr": "सार्वजनिक गृहनिर्माण वाटप योजना", "department": "Housing Department",
    "departmentMr": "गृहनिर्माण विभाग", "category": "Housing",
    "description": "Status verification for citizens who have applied for public housing allotment under a departmental housing scheme.",
    "benefits": "A verified allotment status reference for an applied public housing scheme.",
    "eligibility": "Citizens who have applied for a public housing scheme and meet the scheme's income category.",
    "applicationWindow": "Subject to the current housing scheme's application cycle.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "HOUSING_ALLOTMENT", "label": "Housing allotment status", "mandatory": True},
    ],
}, {
    "id": "SKE-CERTIFICATION-2026", "name": "Skill Certification & Employment Assistance",
    "nameMr": "कौशल्य प्रमाणपत्र व रोजगार सहाय्य", "department": "Skill Development, Employment & Entrepreneurship Department",
    "departmentMr": "कौशल्य विकास, रोजगार व उद्योजकता विभाग", "category": "Skill Development & Employment",
    "description": "Verification of a citizen's skill certification and employment exchange registration for use in job placement and further training programmes.",
    "benefits": "A verified skill certification reference recognised across department employment programmes.",
    "eligibility": "Citizens registered with the Skill Development & Employment Department.",
    "applicationWindow": "Available year-round.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "SKILL_CERTIFICATION", "label": "Skill certification", "mandatory": True},
    ],
}, {
    "id": "MUN-BIRTH-CERT-2026", "name": "Birth Registration Certificate Assistance",
    "nameMr": "जन्म नोंदणी प्रमाणपत्र सहाय्य", "department": "Urban local body civil registration + Public Health Department",
    "departmentMr": "नागरी स्थानिक स्वराज्य संस्था नागरी नोंदणी व सार्वजनिक आरोग्य विभाग", "category": "Civil Registration & Public Health",
    "description": "Assistance verifying an existing birth registration certificate held with the municipal civil registration authority.",
    "benefits": "A verified birth registration reference usable for identity and enrolment purposes.",
    "eligibility": "Citizens with a birth registered with a Maharashtra municipal authority.",
    "applicationWindow": "Available year-round.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "BIRTH_CERTIFICATE", "label": "Birth certificate", "mandatory": True},
    ],
}, {
    "id": "SW-ENROLLMENT-2026", "name": "Social Welfare Scheme Enrollment Assistance",
    "nameMr": "समाज कल्याण योजना नोंदणी सहाय्य", "department": "Social Justice & Special Assistance Department",
    "departmentMr": "सामाजिक न्याय व विशेष सहाय्य विभाग", "category": "Social Welfare",
    "description": "Verification of a citizen's enrollment status in a Social Welfare Department scheme.",
    "benefits": "A verified enrollment status reference for the citizen's welfare scheme.",
    "eligibility": "Citizens already enrolled, or applying for enrollment, in a Social Welfare Department scheme.",
    "applicationWindow": "Available year-round.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "SCHEME_ENROLLMENT_STATUS", "label": "Welfare scheme enrollment", "mandatory": True},
    ],
}, {
    "id": "REV-LAND-VERIFY-2026", "name": "Land Record Verification Service",
    "nameMr": "जमीन अभिलेख पडताळणी सेवा", "department": "Revenue & Forests Department (Maharashtra)",
    "departmentMr": "महसूल व वन विभाग", "category": "Revenue",
    "description": "On-demand verification of a citizen's land-holding (7/12 extract style) record with the Revenue Department.",
    "benefits": "A verified land-holding reference for use wherever proof of land record is required.",
    "eligibility": "Landholders with a record in the Revenue Department.",
    "applicationWindow": "Available year-round.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "LAND_HOLDING", "label": "Land holding record", "mandatory": True},
    ],
}]


# Development fallback catalog. Production selection reads the PostgreSQL catalog.
DEPENDENCY_SERVICES = [
    {
        "requirementCode": "INCOME_PROOF", "requiredService": "Income Verification",
        "serviceName": "Income Verification", "provider": "Revenue Department",
        "adapter": "REST API", "serviceId": "REV-INCOME-102", "sandboxHandler": "income_fetch", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "CASTE_PROOF", "requiredService": "Caste Verification",
        "serviceName": "Caste Verification", "provider": "Social Welfare Department",
        "adapter": "Legacy SOAP Wrapper", "serviceId": "SW-CASTE-301", "sandboxHandler": "caste_fetch", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "DOMICILE_PROOF", "requiredService": "Domicile Certificate",
        "serviceName": "Domicile Issuance", "provider": "Revenue Department",
        "adapter": "REST API", "serviceId": "REV-MAHA-101", "sandboxHandler": "domicile_issue", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "ACADEMIC_RECORD", "requiredService": "Academic Record",
        "serviceName": "Academic Verification", "provider": "Education Department",
        "adapter": "CSV/File Adapter", "serviceId": "EDU-ACA-201", "sandboxHandler": "academic_fetch", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "BANK_DETAILS", "requiredService": "Bank Status",
        "serviceName": "DBT Account Verification", "provider": "Authorized DBT",
        "adapter": "REST API", "serviceId": "DBT-BANK-401", "sandboxHandler": "bank_fetch", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
]


def get_scheme(scheme_id: str):
    try:
        from app.core.persistence import catalog_snapshot
        configured = catalog_snapshot()["schemes"]
    except Exception as error:
        if not _demo_fallback_enabled():
            raise CatalogConfigurationError("Configured service catalog is unavailable") from error
        configured = []
    if not configured and not _demo_fallback_enabled():
        return None
    return next((s for s in (configured or SCHEMES) if s["id"] == scheme_id), None)


def dependency_registry(health: list[dict]) -> list[dict]:
    try:
        from app.core.persistence import provider_capability_snapshot
        definitions = provider_capability_snapshot()
    except Exception as error:
        if not _demo_fallback_enabled():
            raise CatalogConfigurationError("Provider capability catalog is unavailable") from error
        definitions = []
    if not definitions:
        if not _demo_fallback_enabled():
            return []
        definitions = DEPENDENCY_SERVICES
    health_by_provider = {}
    for item in health:
        for key in (item.get("system"), item.get("provider"), item.get("providerId")):
            if key:
                health_by_provider[key] = item
    return [{**definition, "healthStatus": health_by_provider.get(definition.get("providerId"), health_by_provider.get(definition.get("provider"), {})).get("status", "UNAVAILABLE")} for definition in definitions]


def select_dependency_provider(requirement_code: str, health: list[dict]) -> dict | None:
    candidates = [item for item in dependency_registry(health) if item["requirementCode"] == requirement_code]
    eligible = [item for item in candidates if item.get("healthStatus") in {"AVAILABLE", "HEALTHY"}]
    if not eligible:
        return None
    return sorted(eligible, key=lambda item: (item.get("priority", 100), item["provider"]))[0]
