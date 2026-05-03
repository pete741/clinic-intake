/**
 * Submits the completed intake form to the FastAPI backend.
 *
 * The backend URL is read from the NEXT_PUBLIC_API_URL environment variable
 * (defaults to http://localhost:8000 for local development).
 *
 * Returns the parsed JSON response on success, or throws an Error with a
 * human-readable message on failure. The form page catches this and shows
 * it inline without losing any form data.
 */

export interface FormData {
  // Step 1
  clinic_name: string;
  first_name: string;
  email: string;
  phone: string;
  primary_specialty: string;
  suburb: string;
  state: string;
  num_practitioners: number | "";
  website_url: string;

  // Step 2
  avg_appointment_fee: number | "";
  avg_visits_per_patient: number | "";
  new_patients_per_month: number | "";
  monthly_ad_spend: number | "";
  appointment_types_to_grow: string;

  // Step 3
  main_goal: string;
  additional_context: string;

  // Step 4
  has_google_ads: string;
  invite_sent: string;
}

export async function submitForm(data: FormData): Promise<{ status: string; message: string }> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const response = await fetch(`${apiUrl}/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    // Try to parse a detail message from FastAPI's error response
    let detail = `Server error (${response.status})`;
    try {
      const err = await response.json();
      if (err.detail) detail = err.detail;
    } catch (_) {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  return response.json();
}
