"use client";

/**
 * Main intake form page.
 *
 * Manages all form state in one object and passes slices down to each step.
 * Steps 1–3 call onNext() to advance; step 4 calls onSubmit() to POST the data.
 *
 * On success → redirect to /thank-you
 * On error   → show inline error, keep all form data intact
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import ProgressBar from "../components/ProgressBar";
import StepClinic from "../components/StepClinic";
import StepRevenue from "../components/StepRevenue";
import StepGoals from "../components/StepGoals";
import StepGoogleAds from "../components/StepGoogleAds";
import { FormData, submitForm } from "../lib/submitForm";

// Blank initial state: all fields start empty
const INITIAL_FORM_DATA: FormData = {
  clinic_name: "",
  first_name: "",
  email: "",
  phone: "",
  primary_specialty: "",
  suburb: "",
  state: "",
  num_practitioners: "",
  website_url: "",
  avg_appointment_fee: "",
  avg_visits_per_patient: "",
  new_patients_per_month: "",
  monthly_ad_spend: "",
  appointment_types_to_grow: "",
  main_goal: "",
  additional_context: "",
  has_google_ads: "",
  invite_sent: "",
};

const TOTAL_STEPS = 4;

export default function IntakePage() {
  const router = useRouter();

  const [step, setStep] = useState(1);
  const [formData, setFormData] = useState<FormData>(INITIAL_FORM_DATA);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  // Merge partial updates into the shared form data object
  function handleChange(updates: Partial<FormData>) {
    setFormData((prev) => ({ ...prev, ...updates }));
  }

  function goNext() {
    setStep((s) => Math.min(s + 1, TOTAL_STEPS));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function goBack() {
    setStep((s) => Math.max(s - 1, 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleSubmit(overrides?: Partial<FormData>) {
    setIsSubmitting(true);
    setSubmitError("");

    const payload = { ...formData, ...overrides };

    try {
      await submitForm(payload);
      router.push("/thank-you");
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setSubmitError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  // The skip link on step 4 sets invite_sent to "skipped" then submits
  async function handleSkipAds() {
    await handleSubmit({ invite_sent: "skipped" });
  }

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Branding */}
        <div className="mb-6 text-center">
          <p className="text-sm font-semibold text-blue-600 tracking-wide uppercase mb-1">
            Clinic Mastery
          </p>
          <h1 className="text-3xl font-bold text-gray-900">Your free growth brief</h1>
          <p className="mt-2 text-gray-500 text-sm">
            Takes about 3 minutes. We use this to build a personalised plan for your clinic.
          </p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
          <ProgressBar currentStep={step} totalSteps={TOTAL_STEPS} />

          {/* Global submission error (shown below the progress bar) */}
          {submitError && (
            <div className="mb-6 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {submitError}
            </div>
          )}

          {step === 1 && (
            <StepClinic data={formData} onChange={handleChange} onNext={goNext} />
          )}

          {step === 2 && (
            <StepRevenue
              data={formData}
              onChange={handleChange}
              onNext={goNext}
              onBack={goBack}
            />
          )}

          {step === 3 && (
            <StepGoals
              data={formData}
              onChange={handleChange}
              onNext={goNext}
              onBack={goBack}
            />
          )}

          {step === 4 && (
            <StepGoogleAds
              data={formData}
              onChange={handleChange}
              onSubmit={() => handleSubmit()}
              onSkipAds={handleSkipAds}
              onBack={goBack}
              isSubmitting={isSubmitting}
            />
          )}
        </div>

        {/* Footer */}
        <p className="mt-6 text-center text-xs text-gray-400">
          Your information is used only to prepare your growth brief. We don't share it.
        </p>
      </div>
    </main>
  );
}
