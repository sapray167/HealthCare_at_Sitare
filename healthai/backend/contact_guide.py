"""
Dynamic "Whom to Contact" & Field Help Guidance Engine.

Resolves contact information and instructions dynamically without hardcoding a single site,
adapting to whichever insurer/portal is identified (e.g. PolicyBazaar, InsuranceDekho, Star Health,
Niva Bupa, ICICI Lombard, CMS, etc.) or field category.
"""

import re

# Known insurance portals and platforms dictionary for dynamic contact resolution
PLATFORM_DIRECTORY = {
    "policybazaar": {
        "key": "policybazaar",
        "name": "PolicyBazaar Claims & Verification Portal",
        "phone": "1800-258-5888",
        "email": "claims@policybazaar.com",
        "portal": "https://www.policybazaar.com/claim/"
    },
    "insurancedekho": {
        "key": "insurancedekho",
        "name": "InsuranceDekho Customer Support Desk",
        "phone": "7551-196-989",
        "email": "support@insurancedekho.com",
        "portal": "https://www.insurancedekho.com/claims"
    },
    "star health": {
        "key": "star health",
        "name": "Star Health TPA & Customer Desk",
        "phone": "1800-425-2255",
        "email": "support@starhealth.in",
        "portal": "https://www.starhealth.in/claims"
    },
    "hdfc ergo": {
        "key": "hdfc ergo",
        "name": "HDFC ERGO General Insurance Helpdesk",
        "phone": "022-6234-6234",
        "email": "care@hdfcergo.com",
        "portal": "https://www.hdfcergo.com/claims"
    },
    "niva bupa": {
        "key": "niva bupa",
        "name": "Niva Bupa Health Services Desk",
        "phone": "1860-500-8888",
        "email": "customercare@nivabupa.com",
        "portal": "https://www.nivabupa.com/claims"
    },
    "icici lombard": {
        "key": "icici lombard",
        "name": "ICICI Lombard Health Claims Team",
        "phone": "1800-2666",
        "email": "ihealth@icicilombard.com",
        "portal": "https://www.icicilombard.com/claims"
    },
    "care health": {
        "key": "care health",
        "name": "Care Health Insurance TPA Cell",
        "phone": "1800-102-4488",
        "email": "customerfirst@careinsurance.com",
        "portal": "https://www.careinsurance.com/claims"
    }
}

DEFAULT_PLATFORM = {
    "key": "default",
    "name": "Insurance Broker / Payer Claims Helpdesk",
    "phone": "1800-100-2020",
    "email": "support@insurance-desk.org",
    "portal": "https://www.insurance-desk.org/claims"
}


def list_platforms() -> list[dict]:
    """Returns list of supported platforms for dynamic frontend selection."""
    platforms = [{"key": p["key"], "name": p["name"]} for p in PLATFORM_DIRECTORY.values()]
    platforms.append({"key": DEFAULT_PLATFORM["key"], "name": DEFAULT_PLATFORM["name"]})
    return platforms


def detect_platform(filename: str = "", fields_dict: dict = None, platform_key: str = None) -> dict:
    """Dynamically detects or selects issuing platform / insurance vendor context."""
    if platform_key:
        key_clean = platform_key.strip().lower()
        if key_clean in PLATFORM_DIRECTORY:
            return PLATFORM_DIRECTORY[key_clean]
        for k, v in PLATFORM_DIRECTORY.items():
            if k in key_clean or key_clean in k:
                return v

    text_to_search = (filename or "").lower()
    
    if fields_dict:
        for k, v in fields_dict.items():
            if isinstance(v, dict):
                val = str(v.get("value", "")).lower()
                text_to_search += " " + val
            elif isinstance(v, str):
                text_to_search += " " + str(v).lower()

    for key, info in PLATFORM_DIRECTORY.items():
        if key in text_to_search:
            return info
            
    return DEFAULT_PLATFORM


def get_field_guidance(field_key: str, field_label: str, platform_info: dict) -> dict:
    """Generates dynamic guidance & 'Whom to Contact' details for a specific missing field."""
    key_lower = field_key.lower()
    platform_name = platform_info["name"]
    phone = platform_info["phone"]
    email = platform_info["email"]
    portal = platform_info.get("portal", "")

    if any(term in key_lower for term in ["policy", "group_number", "member_id", "plan"]):
        return {
            "hint": f"Check page 1 top header of your policy certificate or e-card issued by {platform_name}. Look for 'Policy Number' or 'Member ID'.",
            "contact": f"{platform_name} — Policy Verification Desk",
            "phone": phone,
            "email": email,
            "portal": portal
        }
    elif any(term in key_lower for term in ["npi", "provider", "tax_id", "physician", "doctor", "facility"]):
        return {
            "hint": "Check the hospital letterhead, attending doctor stamp, or National Provider Identifier (NPI) directory.",
            "contact": "Hospital Billing & Provider Credentials Office",
            "phone": "Contact Hospital Main Desk / TPA Cell",
            "email": "billing@hospital.org",
            "portal": portal
        }
    elif any(term in key_lower for term in ["icd", "diagnosis", "cpt", "procedure", "treatment", "clinical"]):
        return {
            "hint": "Consult the medical chart, discharge summary, or attending doctor's clinical prescription for ICD-10 / CPT diagnosis codes.",
            "contact": "Attending Physician / Medical Records Department",
            "phone": "Ext. 402 (Medical Coding Desk)",
            "email": "records@hospital.org",
            "portal": portal
        }
    elif any(term in key_lower for term in ["amount", "cost", "charge", "total", "billing"]):
        return {
            "hint": "Refer to the itemized hospital estimate bill or pre-authorization breakdown slip.",
            "contact": "Hospital Accounts & Financial Desk",
            "phone": "Ext. 108 (Patient Accounts)",
            "email": "accounts@hospital.org",
            "portal": portal
        }
    elif any(term in key_lower for term in ["patient", "dob", "birth", "gender", "address", "ssn", "phone"]):
        return {
            "hint": f"Enter patient details as printed on national identity card, government ID, or registration portal at {platform_name}.",
            "contact": f"Patient Intake Desk / {platform_name} Member Services",
            "phone": phone,
            "email": email,
            "portal": portal
        }
    else:
        return {
            "hint": f"If uncertain, contact {platform_name} customer support or your hospital administrative coordinator for confirmation.",
            "contact": platform_name,
            "phone": phone,
            "email": email,
            "portal": portal
        }

