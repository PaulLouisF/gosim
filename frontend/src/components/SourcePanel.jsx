const TIER_CONFIG = {
  high:    { color: "text-green-400",  bg: "bg-green-500/10",  border: "border-green-500/20",  label: "●" },
  medium:  { color: "text-yellow-400", bg: "bg-yellow-500/10", border: "border-yellow-500/20", label: "●" },
  low:     { color: "text-red-400",    bg: "bg-red-500/10",    border: "border-red-500/20",    label: "●" },
  discard: { color: "text-white/30",   bg: "bg-white/3",       border: "border-white/5",       label: "✗" },
}

export default function SourcePanel({ sources, onRemove, onOpen }) {
  if (!sources.length) {
    return (
      <div className="p-4 text-center text-white/20 text-xs pt-8">
        No sources yet.<br />Research a topic to see sources here.
      </div>
    )
  }

  const grouped = {
    high:    sources.filter(s => s.confidence_tier === "high"),
    medium:  sources.filter(s => s.confidence_tier === "medium"),
    low:     sources.filter(s => s.confidence_tier === "low"),
    discard: sources.filter(s => s.confidence_tier === "discard"),
  }

  return (
    <div className="p-4 space-y-4">
      <div className="text-xs font-bold uppercase tracking-widest text-white/20">
        Sources ({sources.length})
      </div>
      {Object.entries(grouped).map(([tier, tierSources]) => {
        if (!tierSources.length) return null
        const cfg = TIER_CONFIG[tier]
        return (
          <div key={tier}>
            <div className={`text-xs font-semibold mb-2 ${cfg.color}`}>
              {cfg.label} {tier.charAt(0).toUpperCase() + tier.slice(1)} ({tierSources.length})
            </div>
            <div className="space-y-2">
              {tierSources.map(src => (
                <div
                  key={src.id}
                  className={`rounded-lg border p-2.5 ${cfg.bg} ${cfg.border}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-semibold text-white/80 truncate">
                        {src.title}
                      </div>
                      {src.url && (
                        <div className="text-xs text-white/30 truncate">{src.domain}</div>
                      )}
                      <div className={`text-xs ${cfg.color} mt-0.5`}>
                        {(src.final_confidence * 100).toFixed(0)}% confidence
                      </div>
                      {src.flagged_reason && (
                        <div className="text-xs text-orange-400 mt-0.5">
                          ⚠ {src.flagged_reason}
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col gap-1 flex-shrink-0">
                      {src.url && (
                        <button
                          onClick={() => onOpen(src)}
                          className="text-xs text-white/30 hover:text-white/60 transition-colors"
                          title="Open source"
                        >
                          ↗
                        </button>
                      )}
                      <button
                        onClick={() => onRemove(src)}
                        className="text-xs text-red-400/50 hover:text-red-400 transition-colors"
                        title="Remove source"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
