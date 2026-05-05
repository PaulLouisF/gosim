const SCORE_CONFIG = {
  strong:  { color: "bg-green-500",  text: "text-green-400",  label: "✓" },
  partial: { color: "bg-yellow-500", text: "text-yellow-400", label: "~" },
  missed:  { color: "bg-red-500",    text: "text-red-400",    label: "✗" }
}

export default function GapTracker({ gaps }) {
  const strong  = gaps.filter(g => g.score === "strong").length
  const partial = gaps.filter(g => g.score === "partial").length
  const missed  = gaps.filter(g => g.score === "missed").length

  return (
    <div className="p-4 space-y-3">
      <div className="text-xs font-bold uppercase tracking-widest text-white/20">
        Quiz Performance
      </div>
      <div className="grid grid-cols-3 gap-1.5 text-center">
        {[["Strong", strong, "text-green-400"],
          ["Partial", partial, "text-yellow-400"],
          ["Gap", missed, "text-red-400"]].map(([l, c, col]) => (
          <div key={l} className="bg-white/3 rounded-lg py-2">
            <div className={`text-lg font-bold ${col}`}>{c}</div>
            <div className="text-xs text-white/20">{l}</div>
          </div>
        ))}
      </div>
      <div className="space-y-1.5 max-h-40 overflow-y-auto">
        {gaps.map((g, i) => {
          const cfg = SCORE_CONFIG[g.score] || SCORE_CONFIG.missed
          return (
            <div key={i} className="flex items-start gap-2">
              <div className={`w-4 h-4 rounded flex items-center justify-center
                              text-xs font-bold flex-shrink-0 mt-0.5 ${cfg.color}`}>
                {cfg.label}
              </div>
              <div>
                <div className={`text-xs font-semibold ${cfg.text}`}>{g.concept}</div>
                {g.concept_missed && (
                  <div className="text-xs text-white/25">{g.concept_missed}</div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
