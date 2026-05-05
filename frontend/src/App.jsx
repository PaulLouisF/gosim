import { useState, useEffect, useRef } from "react"
import axios from "axios"
import VoiceBar from "./components/VoiceBar"
import ConversationFeed from "./components/ConversationFeed"
import ReasoningPanel from "./components/ReasoningPanel"
import SourcePanel from "./components/SourcePanel"
import SettingsPanel from "./components/SettingsPanel"
import UploadZone from "./components/UploadZone"
import GapTracker from "./components/GapTracker"

const API = "http://localhost:8000"

function browserSpeak(text) {
  if (!text || !window.speechSynthesis) return
  window.speechSynthesis.cancel()
  const utt = new SpeechSynthesisUtterance(text)
  utt.rate = 1.05
  utt.pitch = 1.0
  window.speechSynthesis.speak(utt)
}

function playAudioOrFallback(arrayBuffer, fallbackText) {
  if (arrayBuffer && arrayBuffer.byteLength > 0) {
    const blob = new Blob([arrayBuffer], { type: "audio/mpeg" })
    new Audio(URL.createObjectURL(blob)).play()
  } else if (fallbackText) {
    browserSpeak(fallbackText)
  }
}

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [reasoning, setReasoning] = useState([])
  const [sources, setSources] = useState([])
  const [gaps, setGaps] = useState([])
  const [wikiPages, setWikiPages] = useState([])
  const [config, setConfig] = useState({ num_sources: 5, search_depth: "basic" })
  const [showSettings, setShowSettings] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [activeQuestion, setActiveQuestion] = useState(null)
  const wsRef = useRef(null)

  useEffect(() => {
    axios.post(`${API}/api/session/start`).then(({ data }) => {
      setSessionId(data.session_id)
    })
  }, [])

  useEffect(() => {
    if (!sessionId) return
    const ws = new WebSocket(`ws://localhost:8000/ws/${sessionId}`)
    wsRef.current = ws

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)

      if (data.event === "reasoning") {
        setReasoning(prev => {
          const idx = prev.findIndex(s => s.type === data.step.type)
          if (idx >= 0) {
            const updated = [...prev]
            updated[idx] = data.step
            return updated
          }
          return [...prev, data.step]
        })
        // Auto-clear panel 2s after the compile step finishes
        if (data.step.type === "compile" && data.step.status === "done") {
          setTimeout(() => setReasoning([]), 2000)
        }
      }

      if (data.event === "wiki_updated") {
        axios.get(`${API}/api/wiki/pages`).then(({ data: d }) => {
          setWikiPages(d.pages)
        })
        if (data.pages) {
          setWikiPages(prev => {
            const existing = new Map(prev.map(p => [p.concept, p]))
            data.pages.forEach(p => existing.set(p.concept, p))
            return Array.from(existing.values())
          })
        }
        if (data.sources) setSources(data.sources)
      }

      if (data.event === "answer_assessed") {
        setGaps(data.gaps || [])
      }

      if (data.event === "show_sources") {
        setSources(data.sources || [])
      }

      if (data.event === "source_removed") {
        setSources(prev => prev.filter(s => s.id !== data.source_id))
      }

      if (data.event === "open_source") {
        if (data.url) window.open(data.url, "_blank")
      }

      if (data.event === "file_uploaded") {
        setSources(prev => [...prev, data.source])
      }

      if (data.event === "study_plan") {
        addMessage("agent", "Study plan ready. Check the gap tracker for details.", "study_plan", data.plan)
      }
    }

    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
    }
  }, [sessionId])

  const addMessage = (role, text, type = "text", data = null) => {
    setMessages(prev => [...prev, {
      id: Date.now(),
      role,
      text,
      type,
      data,
      timestamp: new Date().toLocaleTimeString()
    }])
  }

  const handleTranscript = async (transcript) => {
    if (!sessionId || !transcript.trim()) return
    addMessage("user", transcript)
    setReasoning([])

    try {
      const response = await axios.post(
        `${API}/api/session/${sessionId}/message`,
        { session_id: sessionId, transcript },
        { responseType: "arraybuffer" }
      )

      const text = response.headers["x-text"] || ""
      const questionId = response.headers["x-question-id"]
      const concept = response.headers["x-concept"]

      if (text) addMessage("agent", text)

      if (questionId) {
        setActiveQuestion({ id: questionId, concept, text })
      }

      playAudioOrFallback(response.data, text)
    } catch (err) {
      console.error("Message error:", err)
      addMessage("agent", "Something went wrong. Please try again.")
    }
  }

  const handleAnswer = async (transcript) => {
    if (!activeQuestion || !sessionId) return
    addMessage("user", transcript)

    try {
      const response = await axios.post(
        `${API}/api/session/${sessionId}/answer`,
        { session_id: sessionId, question_id: activeQuestion.id, answer: transcript },
        { responseType: "arraybuffer" }
      )

      const text = response.headers?.["x-text"]
      const score = response.headers?.["x-score"]

      if (text) {
        addMessage("agent", text, "answer", { score })
        playAudioOrFallback(response.data, text)
      }

      setActiveQuestion(null)
    } catch (err) {
      console.error("Answer error:", err)
    }
  }

  const handleVoiceInput = (transcript) => {
    if (activeQuestion) {
      handleAnswer(transcript)
    } else {
      handleTranscript(transcript)
    }
  }

  return (
    <div className="min-h-screen bg-[#0d0d14] text-white font-mono flex flex-col">
      {/* Header */}
      <header className="border-b border-white/5 px-6 py-3 flex items-center gap-3">
        <div className="w-7 h-7 rounded bg-gradient-to-br from-violet-500 to-blue-600
                        flex items-center justify-center text-xs font-bold">S</div>
        <span className="font-bold tracking-tight">Sensei Wiki</span>
        <span className="text-white/20 text-xs">
          {wikiPages.length > 0 ? `${wikiPages.length} concepts compiled` : "No knowledge base yet"}
        </span>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => setShowUpload(!showUpload)}
            className="px-3 py-1 text-xs border border-white/10 rounded
                       hover:border-white/30 transition-all"
          >
            Upload
          </button>
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="px-3 py-1 text-xs border border-white/10 rounded
                       hover:border-white/30 transition-all"
          >
            Settings
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left — Main conversation area */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 overflow-y-auto p-6">
            {messages.length === 0 && (
              <div className="text-center py-20 space-y-4">
                <div className="text-4xl font-bold bg-gradient-to-r from-violet-400
                               to-blue-400 bg-clip-text text-transparent">
                  Sensei Wiki
                </div>
                <p className="text-white/30 text-sm max-w-sm mx-auto leading-relaxed">
                  Say a topic to research. Ask questions. Get quizzed.
                  Add voice notes. All domains. All yours.
                </p>
                <div className="flex flex-wrap gap-2 justify-center mt-6">
                  {[
                    "I want to learn about heart failure",
                    "Quiz me on what you know",
                    "Add a note: remember to check ejection fraction",
                    "Review my sources"
                  ].map(s => (
                    <button
                      key={s}
                      onClick={() => handleTranscript(s)}
                      className="px-3 py-1.5 text-xs border border-white/10
                                 rounded-full text-white/40 hover:text-white/70
                                 hover:border-white/30 transition-all"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <ConversationFeed messages={messages} />
          </div>

          {reasoning.length > 0 && (
            <ReasoningPanel steps={reasoning} />
          )}

          <div className="border-t border-white/5 p-4">
            {activeQuestion && (
              <div className="mb-3 px-4 py-2 bg-violet-500/10 border border-violet-500/20
                             rounded-lg text-sm text-violet-300">
                Answer the question above, or say "skip" to move on
              </div>
            )}
            <VoiceBar sessionId={sessionId} onTranscript={handleVoiceInput} />
          </div>
        </div>

        {/* Right sidebar */}
        <div className="w-80 border-l border-white/5 flex flex-col overflow-hidden relative">
          {showSettings && (
            <SettingsPanel
              config={config}
              onUpdate={async (newConfig) => {
                setConfig(newConfig)
                if (sessionId) {
                  await axios.put(
                    `${API}/api/session/${sessionId}/config`,
                    { ...newConfig, speak_reasoning: false }
                  )
                }
                setShowSettings(false)
              }}
              onClose={() => setShowSettings(false)}
            />
          )}

          {showUpload && (
            <UploadZone
              sessionId={sessionId}
              onUploaded={() => setShowUpload(false)}
            />
          )}

          <div className="flex-1 overflow-y-auto">
            <SourcePanel
              sources={sources}
              onRemove={(source) => handleTranscript(`remove source ${source.title}`)}
              onOpen={(source) => handleTranscript(`open source ${source.title}`)}
            />
          </div>

          {gaps.length > 0 && (
            <div className="border-t border-white/5">
              <GapTracker gaps={gaps} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
