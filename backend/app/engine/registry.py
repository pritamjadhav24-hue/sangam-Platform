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
    "descriptionMr": "वर्ग १० नंतर उच्च शिक्षण घेणाऱ्या पात्र विद्यार्थ्यांसाठी आर्थिक सहाय्य, उत्पन्न, जात, अधिवास व शैक्षणिक नोंदींची आपोआप पडताळणी करून दिले जाते.",
    "benefits": "Tuition and maintenance allowance for the academic year, disbursed directly to the student's linked bank account.",
    "benefitsMr": "शैक्षणिक वर्षासाठी शिकवणी व निर्वाह भत्ता, विद्यार्थ्याच्या संलग्न बँक खात्यात थेट जमा केला जातो.",
    "eligibility": "Maharashtra domicile students enrolled in a recognised post-matric course, subject to family income and category criteria.",
    "eligibilityMr": "महाराष्ट्राचे अधिवास असलेले व मान्यताप्राप्त पदव्युत्तर अभ्यासक्रमात प्रवेशित विद्यार्थी, कौटुंबिक उत्पन्न व प्रवर्ग निकषांच्या अधीन.",
    "applicationWindow": "Applications open for the current academic year.",
    "applicationWindowMr": "चालू शैक्षणिक वर्षासाठी अर्ज सुरू आहेत.",
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
    "descriptionMr": "शिष्यवृत्ती अर्जाशिवाय, विद्यार्थ्याच्या शैक्षणिक नोंदीची शिक्षण विभागाकडे थेट स्वतंत्र पडताळणी.",
    "benefits": "A verified academic record reference usable wherever proof of enrolment or marks is required.",
    "benefitsMr": "नोंदणी किंवा गुणांचा पुरावा आवश्यक असेल तेथे वापरता येणारा पडताळणीकृत शैक्षणिक नोंद संदर्भ.",
    "eligibility": "Any citizen with a recorded academic history in the Education Department.",
    "eligibilityMr": "शिक्षण विभागाकडे नोंदवलेला शैक्षणिक इतिहास असलेला कोणताही नागरिक.",
    "applicationWindow": "Available year-round.",
    "applicationWindowMr": "वर्षभर उपलब्ध.",
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "ACADEMIC_RECORD", "label": "Academic record", "mandatory": True},
    ],
}, {
    "id": "AGR-INPUT-SUBSIDY-2026", "name": "Farmer Input Subsidy Assistance",
    "nameMr": "शेतकरी निविष्ठा अनुदान सहाय्य", "department": "Agriculture, Animal Husbandry, Dairy Development & Fisheries Department",
    "departmentMr": "कृषी, पशुसंवर्धन, दुग्धव्यवसाय विकास व मत्स्यव्यवसाय विभाग", "category": "Agriculture",
    "description": "Support for registered farmers to access subsidised seeds, fertilizers and other farm inputs through their verified land-holding and farmer registration records.",
    "descriptionMr": "नोंदणीकृत शेतकऱ्यांना त्यांच्या पडताळणीकृत जमीन धारणा व शेतकरी नोंदणी अभिलेखांद्वारे अनुदानित बियाणे, खते व इतर शेती निविष्ठा मिळवण्यासाठी सहाय्य.",
    "benefits": "Subsidy support applied toward eligible farm input purchases for the sown season.",
    "benefitsMr": "पेरणी हंगामासाठी पात्र शेती निविष्ठा खरेदीसाठी लागू केलेले अनुदान सहाय्य.",
    "eligibility": "Farmers registered with the Agriculture Department with an active land-holding record.",
    "eligibilityMr": "कृषी विभागाकडे नोंदणीकृत व सक्रिय जमीन धारणा नोंद असलेले शेतकरी.",
    "applicationWindow": "Applications open ahead of each sowing season.",
    "applicationWindowMr": "प्रत्येक पेरणी हंगामापूर्वी अर्ज सुरू होतात.",
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
    "descriptionMr": "नोंदणीचा पुरावा आवश्यक असेल तेथे वापरण्यासाठी, प्रादेशिक परिवहन कार्यालयाकडे नागरिकाच्या वाहन नोंदणी अभिलेखाची मागणीनुसार पडताळणी.",
    "benefits": "A verified vehicle registration reference confirming current registration status.",
    "benefitsMr": "सध्याची नोंदणी स्थिती पुष्टी करणारा पडताळणीकृत वाहन नोंदणी संदर्भ.",
    "eligibility": "Any citizen with a vehicle registered with the Transport Department.",
    "eligibilityMr": "परिवहन विभागाकडे नोंदणीकृत वाहन असलेला कोणताही नागरिक.",
    "applicationWindow": "Available year-round.",
    "applicationWindowMr": "वर्षभर उपलब्ध.",
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
    "descriptionMr": "सार्वजनिक वितरण प्रणालीच्या हक्कांसाठी विद्यमान शिधापत्रिका अभिलेख पडताळणे व जोडण्यासाठी सहाय्य.",
    "benefits": "Verified ration card status enabling continued access to subsidised food-grain entitlements.",
    "benefitsMr": "अनुदानित अन्नधान्य हक्कांचा सतत लाभ घेण्यास सक्षम करणारी पडताळणीकृत शिधापत्रिका स्थिती.",
    "eligibility": "Households already holding, or eligible to hold, a ration card issued by the department.",
    "eligibilityMr": "आधीच शिधापत्रिका धारण करणारी किंवा विभागाने जारी केलेली शिधापत्रिका मिळण्यास पात्र कुटुंबे.",
    "applicationWindow": "Available year-round.",
    "applicationWindowMr": "वर्षभर उपलब्ध.",
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
    "descriptionMr": "विभागीय गृहनिर्माण योजनेअंतर्गत सार्वजनिक गृहनिर्माण वाटपासाठी अर्ज केलेल्या नागरिकांसाठी स्थिती पडताळणी.",
    "benefits": "A verified allotment status reference for an applied public housing scheme.",
    "benefitsMr": "अर्ज केलेल्या सार्वजनिक गृहनिर्माण योजनेसाठी पडताळणीकृत वाटप स्थिती संदर्भ.",
    "eligibility": "Citizens who have applied for a public housing scheme and meet the scheme's income category.",
    "eligibilityMr": "सार्वजनिक गृहनिर्माण योजनेसाठी अर्ज केलेले व योजनेच्या उत्पन्न प्रवर्गात बसणारे नागरिक.",
    "applicationWindow": "Subject to the current housing scheme's application cycle.",
    "applicationWindowMr": "सध्याच्या गृहनिर्माण योजनेच्या अर्ज चक्रानुसार.",
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
    "descriptionMr": "नोकरी नियुक्ती व पुढील प्रशिक्षण कार्यक्रमांमध्ये वापरण्यासाठी नागरिकाच्या कौशल्य प्रमाणपत्राची व रोजगार विनिमय नोंदणीची पडताळणी.",
    "benefits": "A verified skill certification reference recognised across department employment programmes.",
    "benefitsMr": "विभागाच्या सर्व रोजगार कार्यक्रमांमध्ये मान्यताप्राप्त पडताळणीकृत कौशल्य प्रमाणपत्र संदर्भ.",
    "eligibility": "Citizens registered with the Skill Development & Employment Department.",
    "eligibilityMr": "कौशल्य विकास व रोजगार विभागाकडे नोंदणीकृत नागरिक.",
    "applicationWindow": "Available year-round.",
    "applicationWindowMr": "वर्षभर उपलब्ध.",
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
    "descriptionMr": "नागरी स्थानिक स्वराज्य नोंदणी प्राधिकरणाकडे असलेल्या विद्यमान जन्म नोंदणी प्रमाणपत्राची पडताळणी करण्यासाठी सहाय्य.",
    "benefits": "A verified birth registration reference usable for identity and enrolment purposes.",
    "benefitsMr": "ओळख व नोंदणीच्या हेतूंसाठी वापरता येणारा पडताळणीकृत जन्म नोंदणी संदर्भ.",
    "eligibility": "Citizens with a birth registered with a Maharashtra municipal authority.",
    "eligibilityMr": "महाराष्ट्रातील नागरी संस्थेकडे जन्म नोंदणीकृत असलेले नागरिक.",
    "applicationWindow": "Available year-round.",
    "applicationWindowMr": "वर्षभर उपलब्ध.",
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
    "descriptionMr": "समाज कल्याण विभागाच्या योजनेतील नागरिकाच्या नोंदणी स्थितीची पडताळणी.",
    "benefits": "A verified enrollment status reference for the citizen's welfare scheme.",
    "benefitsMr": "नागरिकाच्या कल्याण योजनेसाठी पडताळणीकृत नोंदणी स्थिती संदर्भ.",
    "eligibility": "Citizens already enrolled, or applying for enrollment, in a Social Welfare Department scheme.",
    "eligibilityMr": "समाज कल्याण विभागाच्या योजनेत आधीच नोंदणीकृत किंवा नोंदणीसाठी अर्ज करणारे नागरिक.",
    "applicationWindow": "Available year-round.",
    "applicationWindowMr": "वर्षभर उपलब्ध.",
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
    "descriptionMr": "महसूल विभागाकडे नागरिकाच्या जमीन धारणा (७/१२ उतारा प्रकार) अभिलेखाची मागणीनुसार पडताळणी.",
    "benefits": "A verified land-holding reference for use wherever proof of land record is required.",
    "benefitsMr": "जमीन अभिलेखाचा पुरावा आवश्यक असेल तेथे वापरता येणारा पडताळणीकृत जमीन धारणा संदर्भ.",
    "eligibility": "Landholders with a record in the Revenue Department.",
    "eligibilityMr": "महसूल विभागाकडे नोंद असलेले जमीनधारक.",
    "applicationWindow": "Available year-round.",
    "applicationWindowMr": "वर्षभर उपलब्ध.",
    "synthetic": True,
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "LAND_HOLDING", "label": "Land holding record", "mandatory": True},
    ],
}]


_REQUIREMENT_LABELS_MR = {
    "ACADEMIC_RECORD": "शैक्षणिक नोंद", "BANK_DETAILS": "डीबीटी बँक स्थिती", "BIRTH_CERTIFICATE": "जन्म प्रमाणपत्र",
    "CASTE_PROOF": "जात प्रमाणपत्र", "DOMICILE_PROOF": "महाराष्ट्र अधिवास", "FARMER_REGISTRATION": "शेतकरी नोंदणी",
    "HOUSING_ALLOTMENT": "गृहनिर्माण वाटप स्थिती", "IDENTITY": "ओळख", "INCOME_PROOF": "उत्पन्न प्रमाणपत्र",
    "LAND_HOLDING": "जमीन धारणा नोंद", "RATION_CARD": "शिधापत्रिका", "SCHEME_ENROLLMENT_STATUS": "कल्याण योजना नोंदणी",
    "SKILL_CERTIFICATION": "कौशल्य प्रमाणपत्र", "VEHICLE_REGISTRATION": "वाहन नोंदणी",
}
for _scheme in SCHEMES:
    for _requirement in _scheme["requirements"]:
        _requirement.setdefault("labelMr", _REQUIREMENT_LABELS_MR.get(_requirement["code"], _requirement["label"]))


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
    {
        "requirementCode": "IDENTITY", "requiredService": "Identity Verification",
        "serviceName": "Identity Verification", "provider": "State Resident Registry",
        "adapter": "REST API", "serviceId": "SRR-IDENTITY-001", "sandboxHandler": "identity_verify", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
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
