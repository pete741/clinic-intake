/**
 * Step 2 — Patient and revenue context
 *
 * Collects numbers used to calculate cost-per-patient and set benchmarks.
 * All fields are required.
 */

import React, { useState } from "react";
import { FormData } from "../lib/submitForm";

interface StepRevenueProps {
  data: FormData;
  onChange: (updates: Partial<FormData>) => void;
  onNext: () => void;
  onBack: () => void;
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {hint && <p className="text-xs text-gray-400 mb-1">{hint}</p>}
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

const inputClass =
  "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent";

// Wraps a number input with a currency prefix
function DollarInput({
  value,
  onChange,
  placeholder,
}: {
  value: number | "";
  onChange: (v: number | "") => void;
  placeholder?: string;
}) {
  return (
    <div className="relative">
      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
      <input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(e.target.value ? parseFloat(e.target.value) : "")}
        placeholder={placeholder}
        className={`${inputClass} pl-7`}
      />
    </div>
  );
}

export default function StepRevenue({ data, onChange, onNext, onBack }: StepRevenueProps) {
  const [errors, setErrors] = useState<Partial<Record<keyof FormData, string>>>({});

  function validate(): boolean {
    const e: Partial<Record<keyof FormData, string>> = {};

    if (data.avg_appointment_fee === "" || Number(data.avg_appointment_fee) <= 0)
      e.avg_appointment_fee = "Enter average appointment fee";
    if (data.avg_visits_per_patient === "" || Number(data.avg_visits_per_patient) <= 0)
      e.avg_visits_per_patient = "Enter average visits per patient";
    if (data.new_patients_per_month === "" || Number(data.new_patients_per_month) < 0)
      e.new_patients_per_month = "Enter new patients per month";
    if (data.monthly_ad_spend === "" || Number(data.monthly_ad_spend) < 0)
      e.monthly_ad_spend = "Enter monthly ad spend (enter 0 if not currently running ads)";
    if (!data.appointment_types_to_grow.trim())
      e.appointment_types_to_grow = "Enter at least one appointment type";

    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function handleNext() {
    if (validate()) onNext();
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Patient & revenue context</h2>
        <p className="mt-1 text-sm text-gray-500">
          These numbers help us calculate your true cost per new patient and identify
          where the biggest gains are.
        </p>
      </div>

      <Field
        label="Average appointment fee *"
        hint="The typical fee you charge per appointment, before health fund rebates"
        error={errors.avg_appointment_fee}
      >
        <DollarInput
          value={data.avg_appointment_fee}
          onChange={(v) => onChange({ avg_appointment_fee: v })}
          placeholder="e.g. 95"
        />
      </Field>

      <Field
        label="Average visits per patient *"
        hint="How many appointments does a typical patient attend before they discharge?"
        error={errors.avg_visits_per_patient}
      >
        <input
          type="number"
          min={0}
          step={0.5}
          value={data.avg_visits_per_patient}
          onChange={(e) =>
            onChange({ avg_visits_per_patient: e.target.value ? parseFloat(e.target.value) : "" })
          }
          placeholder="e.g. 6"
          className={inputClass}
        />
      </Field>

      <Field
        label="New patients per month *"
        hint="Approximately how many new patients do you see each month across the whole clinic?"
        error={errors.new_patients_per_month}
      >
        <input
          type="number"
          min={0}
          value={data.new_patients_per_month}
          onChange={(e) =>
            onChange({ new_patients_per_month: e.target.value ? parseInt(e.target.value, 10) : "" })
          }
          placeholder="e.g. 40"
          className={inputClass}
        />
      </Field>

      <Field
        label="Monthly Google Ads spend *"
        hint="Enter 0 if you're not currently running Google Ads"
        error={errors.monthly_ad_spend}
      >
        <DollarInput
          value={data.monthly_ad_spend}
          onChange={(v) => onChange({ monthly_ad_spend: v })}
          placeholder="e.g. 2000"
        />
      </Field>

      <Field
        label="Appointment types you want to grow *"
        hint="What services do you most want to fill? Be specific."
        error={errors.appointment_types_to_grow}
      >
        <input
          type="text"
          value={data.appointment_types_to_grow}
          onChange={(e) => onChange({ appointment_types_to_grow: e.target.value })}
          placeholder="Initial consult, post-surgical rehab, NDIS"
          className={inputClass}
        />
      </Field>

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="text-gray-500 hover:text-gray-700 font-medium px-4 py-2.5 rounded-lg border border-gray-300 hover:border-gray-400 transition-colors"
        >
          ← Back
        </button>
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
