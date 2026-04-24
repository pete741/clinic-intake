/**
 * Thank-you confirmation page.
 * Shown after a successful intake form submission.
 */

import Link from "next/link";

export default function ThankYouPage() {
  return (
    <main className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="max-w-lg w-full bg-white rounded-2xl shadow-sm border border-gray-200 p-10 text-center">
        {/* Success icon */}
        <div className="flex justify-center mb-6">
          <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center">
            <svg
              className="w-8 h-8 text-green-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
        </div>

        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          Your brief is being generated
        </h1>

        <p className="text-gray-500 text-sm mb-6">
          Thanks for taking the time to fill that in. We're putting together your
          personalised growth brief now and will be in touch shortly.
        </p>

        <div className="rounded-lg bg-blue-50 border border-blue-100 px-5 py-4 text-sm text-blue-800 text-left space-y-2 mb-8">
          <p className="font-semibold">What happens next?</p>
          <ul className="space-y-1 text-blue-700">
            <li>• We'll review your intake details</li>
            <li>• Build your personalised growth brief</li>
            <li>• Reach out to schedule a strategy call</li>
          </ul>
        </div>

        {/* Booking CTA */}
        <div className="rounded-xl bg-slate-900 px-6 py-6 text-left mb-6">
          <p className="text-white font-bold text-base mb-1">
            Want Pete to walk you through it personally?
          </p>
          <p className="text-slate-300 text-sm mb-4">
            Once your report is ready, book a free 15-minute call and Pete will show you exactly:
          </p>
          <ul className="space-y-2 text-sm text-slate-200 mb-5">
            <li className="flex items-start gap-2">
              <span className="text-red-400 font-bold mt-0.5">→</span>
              <span>Where your Google Ads budget is being wasted — down to the dollar</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-red-400 font-bold mt-0.5">→</span>
              <span>The specific fixes that will lower your cost-per-lead immediately</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-red-400 font-bold mt-0.5">→</span>
              <span>A realistic projection of what better-managed spend means for your revenue</span>
            </li>
          </ul>
          <a
            href="https://bookings.clinicmastery.com/pete-flynn"
            target="_blank"
            rel="noopener noreferrer"
            className="block w-full text-center bg-red-600 hover:bg-red-700 text-white font-semibold text-sm py-3 px-4 rounded-lg transition-colors"
          >
            Book a Free Report Walk-Through
          </a>
          <p className="text-slate-400 text-xs text-center mt-3">
            15 minutes. No obligation. Just clarity on what&apos;s costing you.
          </p>
        </div>

        <p className="text-xs text-gray-400">
          Questions? Email{" "}
          <a
            href="mailto:pete@clinicmastery.com"
            className="underline hover:text-gray-600"
          >
            pete@clinicmastery.com
          </a>
        </p>
      </div>
    </main>
  );
}
