/**
 * Step 1: About your clinic
 *
 * Collects the basic clinic details. All fields are required.
 * Validation is done here before the parent page advances to step 2.
 */

import { FormData } from "../lib/submitForm";

interface StepClinicProps {
  data: FormData;
  onChange: (updates: Partial<FormData>) => void;
  onNext: () => void;
}

const SPECIALTIES = [
  "Physiotherapy",
  "Chiropractic",
  "Occupational therapy",
  "Podiatry",
  "Psychology",
  "Exercise physiology",
  "Speech pathology",
  "Osteopathy",
  "Other allied health",
];

const STATES = ["QLD", "NSW", "VIC", "WA", "SA", "TAS", "ACT", "NT"];

// Reusable label + input wrapper
function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

const inputClass =
  "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent";

export default function StepClinic({ data, onChange, onNext }: StepClinicProps) {
  // Per-field error state
  const [errors, setErrors] = React.useState<Partial<Record<keyof FormData, string>>>({});

  function validate(): boolean {
    const e: Partial<Record<keyof FormData, string>> = {};

    if (!data.clinic_name.trim()) e.clinic_name = "Clinic name is required";
    if (!data.first_name.trim()) e.first_name = "First name is required";
    if (!data.email.trim()) {
      e.email = "Email is required";
    } else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email)) {
      e.email = "Enter a valid email address";
    }
    if (!data.phone.trim()) {
      e.phone = "Phone number is required";
    } else if (!/^[+\d][\d\s()-]{6,}$/.test(data.phone)) {
      e.phone = "Enter a valid phone number";
    }
    if (!data.primary_specialty) e.primary_specialty = "Please select a specialty";
    if (!data.suburb.trim()) e.suburb = "Suburb is required";
    if (!data.state) e.state = "Please select a state";
    if (data.num_practitioners === "" || Number(data.num_practitioners) < 1)
      e.num_practitioners = "Enter at least 1 practitioner";
    if (!data.website_url.trim()) {
      e.website_url = "Website URL is required";
    } else if (!/^https?:\/\/.+/.test(data.website_url)) {
      e.website_url = "Enter a valid URL starting with http:// or https://";
    }

    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function handleNext() {
    if (validate()) onNext();
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">About your clinic</h2>
        <p className="mt-1 text-sm text-gray-500">
          Tell us the basics. This becomes the foundation of your growth brief.
        </p>
      </div>

      <Field label="Clinic name *" error={errors.clinic_name}>
        <input
          type="text"
          value={data.clinic_name}
          onChange={(e) => onChange({ clinic_name: e.target.value })}
          placeholder="e.g. Bayside Physio"
          className={inputClass}
        />
      </Field>

      <Field label="Your first name *" error={errors.first_name}>
        <input
          type="text"
          value={data.first_name}
          onChange={(e) => onChange({ first_name: e.target.value })}
          placeholder="e.g. Sarah"
          className={inputClass}
          autoComplete="given-name"
        />
      </Field>

      <Field label="Email address *" error={errors.email}>
        <input
          type="email"
          value={data.email}
          onChange={(e) => onChange({ email: e.target.value })}
          placeholder="you@yourclinic.com.au"
          className={inputClass}
          autoComplete="email"
        />
      </Field>

      <Field label="Phone number *" error={errors.phone}>
        <input
          type="tel"
          value={data.phone}
          onChange={(e) => onChange({ phone: e.target.value })}
          placeholder="04xx xxx xxx"
          className={inputClass}
          autoComplete="tel"
        />
      </Field>

      <Field label="Primary specialty *" error={errors.primary_specialty}>
        <select
          value={data.primary_specialty}
          onChange={(e) => onChange({ primary_specialty: e.target.value })}
          className={inputClass}
        >
          <option value="">Select a specialty…</option>
          {SPECIALTIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Suburb *" error={errors.suburb}>
          <input
            type="text"
            value={data.suburb}
            onChange={(e) => onChange({ suburb: e.target.value })}
            placeholder="e.g. Newstead"
            className={inputClass}
          />
        </Field>

        <Field label="State *" error={errors.state}>
          <select
            value={data.state}
            onChange={(e) => onChange({ state: e.target.value })}
            className={inputClass}
          >
            <option value="">Select…</option>
            {STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field label="Number of practitioners *" error={errors.num_practitioners}>
        <input
          type="number"
          min={1}
          value={data.num_practitioners}
          onChange={(e) =>
            onChange({ num_practitioners: e.target.value ? parseInt(e.target.value, 10) : "" })
          }
          className={inputClass}
        />
      </Field>

      <Field label="Website URL *" error={errors.website_url}>
        <input
          type="text"
          value={data.website_url}
          onChange={(e) => onChange({ website_url: e.target.value })}
          placeholder="https://www.yourclinic.com.au"
          className={inputClass}
        />
      </Field>

      <div className="flex justify-end pt-2">
        <button
          onClick={handleNext}
          className="bg-blue-600 hover:bg-blue-700 text-white font-medium px-6 py-2.5 rounded-lg transition-colors"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

// React is available globally in Next.js App Router but we need useState
import React from "react";
