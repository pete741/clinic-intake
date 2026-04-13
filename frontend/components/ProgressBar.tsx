/**
 * ProgressBar — shows "Step X of 4" and a filled bar.
 * The bar fills proportionally: step 1 = 25%, step 2 = 50%, etc.
 */

interface ProgressBarProps {
  currentStep: number; // 1-based
  totalSteps: number;
}

const STEP_LABELS = [
  "About your clinic",
  "Patient & revenue",
  "Goals & context",
  "Google Ads access",
];

export default function ProgressBar({ currentStep, totalSteps }: ProgressBarProps) {
  const pct = Math.round((currentStep / totalSteps) * 100);

  return (
    <div className="mb-8">
      {/* Step label */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-600">
          Step {currentStep} of {totalSteps} — {STEP_LABELS[currentStep - 1]}
        </span>
        <span className="text-sm text-gray-400">{pct}%</span>
      </div>

      {/* Track */}
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className="bg-blue-600 h-2 rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Step dots */}
      <div className="flex justify-between mt-2">
        {Array.from({ length: totalSteps }, (_, i) => (
          <div
            key={i}
            className={`w-2.5 h-2.5 rounded-full transition-colors duration-200 ${
              i + 1 <= currentStep ? "bg-blue-600" : "bg-gray-300"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
