/**
 * Step 4 — Google Ads access (optional)
 *
 * This step has a distinct visual treatment:
 *   - Purple border card
 *   - Before/after comparison panel
 *   - Clear labelling that it's optional but valuable
 *
 * Conditional rendering:
 *   - If has_google_ads is any "Yes" variant → show the invite instructions
 *   - If has_google_ads is "No" → show a reassuring message
 *   - invite_sent dropdown only appears when ads are "Yes"
 *
 * The "Skip Google Ads access" link sets invite_sent to "skipped" and submits.
 */

import React, { useState } from "react";
import { FormData } from "../lib/submitForm";

interface StepGoogleAdsProps {
  data: FormData;
  onChange: (updates: Partial<FormData>) => void;
  onSubmit: () => void;
  onSkipAds: () => void;
  onBack: () => void;
  isSubmitting: boolean;
}

const HAS_ADS_OPTIONS = [
  { value: "", label: "Select an option…" },
  { value: "Yes — I have an active account", label: "Yes — I have an active account" },
  { value: "Yes — managed by another agency", label: "Yes — managed by another agency" },
  { value: "Yes — but paused or inactive", label: "Yes — but paused or inactive" },
  { value: "No — I don't run Google Ads yet", label: "No — I don't run Google Ads yet" },
];

const INVITE_OPTIONS = [
  { value: "", label: "Select one…" },
  { value: "I'll do this after submitting", label: "I'll do this after submitting" },
  { value: "Yes, I've sent the invitation", label: "Yes, I've sent the invitation" },
  { value: "I'd prefer to skip this for now", label: "I'd prefer to skip this for now" },
];

// Green tick icon for the "With access" column
function GreenTick() {
  return (
    <svg
      className="inline-block w-4 h-4 text-green-500 mr-1.5 flex-shrink-0 mt-0.5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2.5}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

const inputClass =
  "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent";

export default function StepGoogleAds({
  data,
  onChange,
  onSubmit,
  onSkipAds,
  onBack,
  isSubmitting,
}: StepGoogleAdsProps) {
  const hasAdsYes =
    data.has_google_ads.startsWith("Yes") && data.has_google_ads !== "";
  const hasAdsNo = data.has_google_ads === "No — I don't run Google Ads yet";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <span className="inline-block bg-purple-100 text-purple-700 text-xs font-semibold px-2.5 py-0.5 rounded-full mb-2">
          Optional but recommended
        </span>
        <h2 className="text-2xl font-bold text-gray-900">
          Unlock a deeper analysis of your Google Ads account
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          Without this we can tell you what's possible. With it we can tell you{" "}
          <span className="font-semibold">exactly what's wrong and what to fix first.</span>
        </p>
      </div>

      {/* Before / After comparison panel */}
      <div className="rounded-xl border-2 border-purple-300 bg-purple-50 p-5">
        <div className="grid grid-cols-2 gap-4 text-sm">
          {/* Without */}
          <div>
            <p className="font-semibold text-gray-700 mb-2">Without access</p>
            <ul className="space-y-1.5 text-gray-500">
              {[
                "Market & competitor overview",
                "Estimated cost per new patient",
                "Benchmark vs similar clinics",
                "Growth opportunity summary",
              ].map((item) => (
                <li key={item} className="flex items-start">
                  <span className="mr-1.5 text-gray-300 mt-0.5">•</span>
                  {item}
                </li>
              ))}
            </ul>
          </div>

          {/* With */}
          <div>
            <p className="font-semibold text-purple-700 mb-2">With access</p>
            <ul className="space-y-1.5 text-gray-700">
              {[
                "Everything on the left, PLUS:",
                "Actual wasted spend identified",
                "Keyword gaps vs competitors",
                "Campaign structure audit",
                "Quality score breakdown",
                "Prioritised fix list before the call",
              ].map((item, i) => (
                <li key={item} className={`flex items-start ${i === 0 ? "italic text-gray-500 text-xs" : ""}`}>
                  {i > 0 && <GreenTick />}
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {/* Has Google Ads dropdown */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Do you currently run Google Ads?
        </label>
        <select
          value={data.has_google_ads}
          onChange={(e) => onChange({ has_google_ads: e.target.value, invite_sent: "" })}
          className={inputClass}
        >
          {HAS_ADS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {/* "Yes" path — invite instructions */}
      {hasAdsYes && (
        <div className="rounded-xl border border-purple-200 bg-white p-5 space-y-4">
          <p className="text-sm font-semibold text-gray-800">
            How to grant read-only access (takes about 2 minutes):
          </p>
          <ol className="space-y-2 text-sm text-gray-700">
            {[
              <>Sign into Google Ads at <span className="font-mono text-xs bg-gray-100 px-1 py-0.5 rounded">ads.google.com</span></>,
              <>Click <strong>Admin</strong> in the left sidebar, then <strong>Access and security</strong></>,
              <>Click <strong>+ Invite users</strong> in the top right</>,
              <>
                Enter our email:{" "}
                <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded select-all">
                  pete@clinicmastery.com
                </span>
              </>,
              <>Set access level to <strong>Read only</strong></>,
              <>Click <strong>Send invitation</strong></>,
            ].map((step, i) => (
              <li key={i} className="flex gap-3">
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-purple-600 text-white text-xs flex items-center justify-center font-bold">
                  {i + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Have you sent the invitation?
            </label>
            <select
              value={data.invite_sent}
              onChange={(e) => onChange({ invite_sent: e.target.value })}
              className={inputClass}
            >
              {INVITE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* "No" path — reassuring message */}
      {hasAdsNo && (
        <div className="rounded-lg bg-blue-50 border border-blue-200 p-4 text-sm text-blue-800">
          No problem — we'll design your initial campaign structure based on your
          market and competitors. You'll get a full launch strategy in your brief.
        </div>
      )}

      {/* Action buttons */}
      <div className="flex justify-between items-center pt-2">
        <button
          onClick={onBack}
          className="text-gray-500 hover:text-gray-700 font-medium px-4 py-2.5 rounded-lg border border-gray-300 hover:border-gray-400 transition-colors"
        >
          ← Back
        </button>

        <button
          onClick={onSubmit}
          disabled={isSubmitting}
          className="bg-purple-600 hover:bg-purple-700 disabled:opacity-60 text-white font-semibold px-7 py-2.5 rounded-lg transition-colors flex items-center gap-2"
        >
          {isSubmitting ? (
            <>
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Generating…
            </>
          ) : (
            "Generate my growth brief →"
          )}
        </button>
      </div>

      {/* Skip link */}
      <div className="text-center">
        <button
          onClick={onSkipAds}
          disabled={isSubmitting}
          className="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2 transition-colors"
        >
          Skip Google Ads access and generate a standard brief
        </button>
      </div>
    </div>
  );
}
