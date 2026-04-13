/**
 * Step 3 — Goals and context
 *
 * Captures what the clinic most wants to achieve and any additional
 * context that helps tailor the brief. The dropdown is required;
 * the textarea is optional.
 */

import React, { useState } from "react";
import { FormData } from "../lib/submitForm";

interface StepGoalsProps {
  data: FormData;
  onChange: (updates: Partial<FormData>) => void;
  onNext: () => void;
  onBack: () => void;
}

const GOALS = [
  "Fill practitioner diaries faster",
  "Reduce cost per new patient",
  "Grow a specific service type",
  "Onboard a new practitioner",
  "Expand to a second location",
  "Understand what's working — I want an audit",
];

const inputClass =
  "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent";

export default function StepGoals({ data, onChange, onNext, onBack }: StepGoalsProps) {
  const [error, setError] = useState("");

  function handleNext() {
    if (!data.main_goal) {
      setError("Please select your main goal");
      return;
    }
    setError("");
    onNext();
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Goals & context</h2>
        <p className="mt-1 text-sm text-gray-500">
          Help us understand what success looks like for you right now.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Main goal *
        </label>
        <select
          value={data.main_goal}
          onChange={(e) => {
            onChange({ main_goal: e.target.value });
            if (e.target.value) setError("");
          }}
          className={inputClass}
        >
          <option value="">Select your primary goal…</option>
          {GOALS.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Additional context{" "}
          <span className="text-gray-400 font-normal">(optional)</span>
        </label>
        <p className="text-xs text-gray-400 mb-1">
          The more context you give, the more specific the brief. What have you tried?
          What's changed recently?
        </p>
        <textarea
          rows={5}
          value={data.additional_context}
          onChange={(e) => onChange({ additional_context: e.target.value })}
          placeholder="Competitors, recent changes, challenges, what's worked before..."
          className={`${inputClass} resize-none`}
        />
      </div>

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
