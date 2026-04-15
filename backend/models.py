"""
Pydantic models for the intake form submission.
All fields map directly to what the frontend sends via POST /submit.
"""

from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator
import re


class IntakeSubmission(BaseModel):
    # Step 1 — About your clinic
    clinic_name: str
    email: str
    primary_specialty: str
    suburb: str
    state: str
    num_practitioners: int
    website_url: str

    # Step 2 — Patient and revenue context
    avg_appointment_fee: float
    avg_visits_per_patient: float
    new_patients_per_month: int
    monthly_ad_spend: float
    appointment_types_to_grow: str

    # Step 3 — Goals and context
    main_goal: str
    additional_context: Optional[str] = None

    # Contact
    phone: Optional[str] = None

    # Step 4 — Google Ads access (entirely optional)
    has_google_ads: Optional[str] = None
    invite_sent: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        # Basic email format check
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("num_practitioners")
    @classmethod
    def validate_practitioners(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Must have at least 1 practitioner")
        return v

    def has_google_ads_yes(self) -> bool:
        """Returns True if any 'Yes' variant was selected for has_google_ads."""
        return self.has_google_ads is not None and self.has_google_ads.startswith("Yes")

    def invite_confirmed(self) -> bool:
        """Returns True if the clinic confirmed they sent the invite."""
        return self.invite_sent == "Yes, I've sent the invitation"
