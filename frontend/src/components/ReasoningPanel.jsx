const STEP_ICONS = {
  orchestrator: "🧠",
  research: "🔍",
  evaluate: "⚖️",
  compile: "📝",
  tutor: "📚",
  note: "📌"
}

const STATUS_COLORS = {
  running: "text-yellow-400",
  done: "text-green-400",
  warning: "text-orange-400",
  error: "text-red-400"
}

export default function ReasoningPanel({ steps }) {
  return (
    <div className="border-t border-white/5 bg-white/2 px-6 py-3 space-y-1.5">
      <div className="text-xs font-bold uppercase tracking-widest text-white/20 mb-2">
        Agent Reasoning
      </div>
      {steps.map((step, i) => (
        <div key={i} className="flex items-start gap-2">
          <span className="text-sm flex-shrink-0">
            {STEP_ICONS[step.type] || "→"}
          </span>
          <div className="flex-1 min-w-0">
            <span className={`text-xs font-semibold ${STATUS_COLORS[step.status]}`}>
              {step.message}
            </span>
            {step.detail && (
              <span className="text-xs text-white/30 ml-2">{step.detail}</span>
            )}
          </div>
          {step.status === "running" && (
            <div className="w-3 h-3 rounded-full border border-yellow-400/50
                           border-t-yellow-400 animate-spin flex-shrink-0 mt-0.5" />
          )}
        </div>
      ))}
    </div>
  )
}
