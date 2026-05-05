import { useState, useRef, useCallback } from "react"

export function useVoice({ onTranscript }) {
  const [listening, setListening] = useState(false)
  const [transcript, setTranscript] = useState("")
  const recognitionRef = useRef(null)
  const latestRef = useRef("")

  const startListening = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return

    const rec = new SR()
    rec.continuous = false
    rec.interimResults = true
    rec.lang = "en-US"

    rec.onresult = (e) => {
      const t = Array.from(e.results).map(r => r[0].transcript).join("")
      setTranscript(t)
      latestRef.current = t
    }
    rec.onend = () => {
      setListening(false)
      const final = latestRef.current
      if (final.trim()) {
        onTranscript(final.trim())
        setTranscript("")
        latestRef.current = ""
      }
    }
    rec.onerror = () => setListening(false)

    recognitionRef.current = rec
    rec.start()
    setListening(true)
    setTranscript("")
    latestRef.current = ""
  }, [onTranscript])

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  return { listening, transcript, startListening, stopListening }
}
