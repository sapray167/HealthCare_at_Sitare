from datetime import date

from schemas import get_schema


def _val(fields: dict, key: str) -> str:
    v = fields.get(key, "")
    return v if v else "[NOT PROVIDED — PLEASE COMPLETE]"


def generate_draft(form_type: str, fields: dict) -> str:
    today = date.today().strftime("%m/%d/%Y")

    if form_type == "prior_authorization":
        return f"""PRIOR AUTHORIZATION REQUEST
Date Prepared: {today}

PATIENT INFORMATION
Name: {_val(fields, 'patient_name')}
Date of Birth: {_val(fields, 'patient_dob')}
Insurance Member ID: {_val(fields, 'insurance_member_id')}
Payer: {_val(fields, 'insurance_payer_name')}

REQUESTING PROVIDER
Name: {_val(fields, 'requesting_provider_name')}
NPI: {_val(fields, 'requesting_provider_npi')}

CLINICAL DETAILS
Diagnosis Code (ICD-10): {_val(fields, 'diagnosis_code')}
Diagnosis Description: {_val(fields, 'diagnosis_description')}
Requested Procedure Code (CPT/HCPCS): {_val(fields, 'procedure_code')}
Procedure Description: {_val(fields, 'procedure_description')}
Requested Date of Service: {_val(fields, 'requested_date_of_service')}
Urgency: {_val(fields, 'urgency')}

CLINICAL JUSTIFICATION
{_val(fields, 'clinical_justification')}

---
This document was drafted by an AI assistant from uploaded source documents.
It must be reviewed and approved by qualified administrative/clinical staff
before submission to the payer.
"""

    elif form_type == "insurance_claim":
        return f"""INSURANCE CLAIM SUBMISSION
Date Prepared: {today}

PATIENT INFORMATION
Name: {_val(fields, 'patient_name')}
Date of Birth: {_val(fields, 'patient_dob')}
Insurance Member ID: {_val(fields, 'insurance_member_id')}
Policy Number: {_val(fields, 'insurance_policy_number')}
Payer: {_val(fields, 'insurance_payer_name')}

PROVIDER INFORMATION
Name: {_val(fields, 'provider_name')}
NPI: {_val(fields, 'provider_npi')}

CLAIM DETAILS
Claim Type: {_val(fields, 'claim_type')}
Date of Service: {_val(fields, 'date_of_service')}
Diagnosis Code(s): {_val(fields, 'diagnosis_codes')}
Procedure Code(s): {_val(fields, 'procedure_codes')}
Total Charge Amount: {_val(fields, 'charge_amount')}

---
This document was drafted by an AI assistant from uploaded source documents.
It must be reviewed and approved by qualified administrative/billing staff
before submission to the payer.
"""

    else:
        raise ValueError(f"Unknown form_type '{form_type}'")
