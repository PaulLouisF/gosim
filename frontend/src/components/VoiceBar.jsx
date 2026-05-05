import { useState, useRef, useCallback } from "react"

export default function VoiceBar({ onTranscript }) {
  const [listening, setListening] = useState(false)
  const [transcript, setTranscript] = useState("")
  const [textInput, setTextInput] = useState("")
  const recognitionRef = useRef(null)
  const latestTranscriptRef = useRef("")

  const startListening = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) {
      alert("Speech recognition not supported. Use Chrome or type below.")
      return
    }
    const rec = new SR()
    rec.continuous = false
    rec.interimResults = true
    rec.lang = "en-US"

    rec.onresult = (e) => {
      const t = Array.from(e.results).map(r => r[0].transcript).join("")
      setTranscript(t)
      latestTranscriptRef.current = t
    }
    rec.onend = () => {
      setListening(false)
      const final = latestTranscriptRef.current
      if (final.trim()) {
        onTranscript(final.trim())
        setTranscript("")
        latestTranscriptRef.current = ""
      }
    }
    rec.onerror = () => setListening(false)

    recognitionRef.current = rec
    rec.start()
    setListening(true)
    setTranscript("")
    latestTranscriptRef.current = ""
  }, [onTranscript])

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  const handleTextSubmit = (e) => {
    e.preventDefault()
    if (textInput.trim()) {
      onTranscript(textInput.trim())
      setTextInput("")
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <button
          onMouseDown={startListening}
          onMouseUp={stopListening}
          onTouchStart={startListening}
          onTouchEnd={stopListening}
          className={`w-12 h-12 rounded-full flex items-center justify-center
                      transition-all duration-200 flex-shrink-0 text-lg
                      ${listening
                        ? "bg-red-500 scale-110 shadow-lg shadow-red-500/30"
                        : "bg-violet-600 hover:bg-violet-500"}`}
        >
          {listening ? "■" : "🎙"}
        </button>

        <div className={`flex-1 h-12 rounded-xl border px-4 flex items-center
                         text-sm transition-all
                         ${listening
                           ? "border-red-500/50 bg-red-500/5"
                           : "border-white/10 bg-white/3"}`}>
          {listening ? (
            <span className="text-white/70 italic">
              {transcript || "Listening..."}
            </span>
          ) : (
            <span className="text-white/25">
              Hold to speak
            </span>
          )}
        </div>

        {listening && (
          <div className="flex gap-0.5 items-center h-8 flex-shrink-0">
            {[1, 2, 3, 4, 5].map(i => (
              <div
                key={i}
                className="w-1 bg-red-400 rounded-full animate-pulse"
                style={{
                  height: `${20 + (i * 4)}px`,
                  animationDelay: `${i * 100}ms`
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Text input fallback */}
      <form onSubmit={handleTextSubmit} className="flex gap-2">
        <input
          type="text"
          value={textInput}
          onChange={e => setTextInput(e.target.value)}
          placeholder="Or type here and press Enter..."
          className="flex-1 h-9 rounded-lg border border-white/10 bg-white/3
                     px-3 text-sm text-white placeholder-white/20
                     focus:outline-none focus:border-violet-500/50"
        />
        <button
          type="submit"
          className="px-4 h-9 rounded-lg bg-violet-600/80 hover:bg-violet-600
                     text-sm font-semibold transition-all"
        >
          Send
        </button>
      </form>
    </div>
  )
}
