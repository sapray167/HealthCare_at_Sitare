"""
Field schemas for the two supported form types.
Add a new form type by adding a new key here — nothing else needs to change
in extractor.py or main.py, they're both schema-driven.
"""

FORM_SCHEMAS = {
    "prior_authorization": {
        "label": "Prior Authorization Request",
        "fields": {
            "patient_name": "Full legal name of the patient",
            "patient_dob": "Patient date of birth (MM/DD/YYYY)",
            "insurance_member_id": "Insurance member / subscriber ID",
            "insurance_payer_name": "Name of the insurance company / payer",
            "requesting_provider_name": "Name of the physician or clinic requesting authorization",
            "requesting_provider_npi": "NPI number of the requesting provider",
            "diagnosis_code": "ICD-10 diagnosis code",
            "diagnosis_description": "Plain-text description of the diagnosis",
            "procedure_code": "CPT/HCPCS procedure or service code being requested",
            "procedure_description": "Plain-text description of the requested procedure/service",
            "requested_date_of_service": "Date the service is planned for (MM/DD/YYYY)",
            "urgency": "Standard or Urgent/Expedited",
            "clinical_justification": "Brief clinical reason/notes supporting medical necessity",
        },
        "required": [
            "patient_name", "patient_dob", "insurance_member_id",
            "requesting_provider_name", "diagnosis_code", "procedure_code",
            "procedure_description",
        ],
    },
    "insurance_claim": {
        "label": "Insurance Claim Submission",
        "fields": {
            "patient_name": "Full legal name of the patient",
            "patient_dob": "Patient date of birth (MM/DD/YYYY)",
            "insurance_member_id": "Insurance member / subscriber ID",
            "insurance_policy_number": "Policy or group number",
            "insurance_payer_name": "Name of the insurance company / payer",
            "provider_name": "Name of the treating physician or facility",
            "provider_npi": "NPI number of the treating provider",
            "date_of_service": "Date service was rendered (MM/DD/YYYY)",
            "diagnosis_codes": "ICD-10 diagnosis code(s), comma separated if multiple",
            "procedure_codes": "CPT/HCPCS procedure code(s) billed, comma separated if multiple",
            "charge_amount": "Total billed charge amount",
            "claim_type": "e.g. Professional, Institutional, Dental",
        },
        "required": [
            "patient_name", "patient_dob", "insurance_member_id",
            "provider_name", "date_of_service", "diagnosis_codes",
            "procedure_codes", "charge_amount",
        ],
    },
}


def get_schema(form_type: str) -> dict:
    if form_type not in FORM_SCHEMAS:
        raise ValueError(f"Unknown form_type '{form_type}'. Valid: {list(FORM_SCHEMAS)}")
    return FORM_SCHEMAS[form_type]
