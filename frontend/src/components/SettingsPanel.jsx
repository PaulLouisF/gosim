import { useState } from "react"

export default function SettingsPanel({ config, onUpdate, onClose }) {
  const [local, setLocal] = useState(config)

  return (
    <div className="absolute top-0 right-0 w-80 h-full bg-[#0d0d14] border-l
                   border-white/10 z-10 p-6 space-y-6 overflow-y-auto">
      <div className="flex items-center justify-between">
        <div className="font-bold text-sm">Settings</div>
        <button onClick={onClose} className="text-white/30 hover:text-white text-lg">✕</button>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-xs text-white/50 uppercase tracking-wide">
            Number of sources
          </label>
          <input
            type="range"
            min={3}
            max={15}
            value={local.num_sources}
            onChange={e => setLocal({ ...local, num_sources: parseInt(e.target.value) })}
            className="w-full mt-2 accent-violet-500"
          />
          <div className="text-xs text-white/40 text-center mt-1">
            {local.num_sources} sources per research
          </div>
        </div>

        <div>
          <label className="text-xs text-white/50 uppercase tracking-wide">
            Search depth
          </label>
          <div className="flex gap-2 mt-2">
            {["basic", "advanced"].map(d => (
              <button
                key={d}
                onClick={() => setLocal({ ...local, search_depth: d })}
                className={`flex-1 py-2 rounded-lg text-sm font-semibold transition-all border
                  ${local.search_depth === d
                    ? "bg-violet-600 border-violet-500 text-white"
                    : "border-white/10 text-white/40 hover:border-white/30"}`}
              >
                {d.charAt(0).toUpperCase() + d.slice(1)}
              </button>
            ))}
          </div>
          <div className="text-xs text-white/30 mt-1">
            Advanced = slower but more thorough
          </div>
        </div>
      </div>

      <button
        onClick={() => onUpdate(local)}
        className="w-full py-3 bg-violet-600 hover:bg-violet-500
                   rounded-xl font-semibold text-sm transition-all"
      >
        Save Settings
      </button>
    </div>
  )
}
