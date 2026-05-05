import { useState, useEffect, useRef } from "react"
import axios from "axios"

const API = "http://localhost:8000"

export function useSession() {
  const [sessionId, setSessionId] = useState(null)
  const [sources, setSources] = useState([])
  const [gaps, setGaps] = useState([])
  const [wikiPages, setWikiPages] = useState([])
  const [reasoning, setReasoning] = useState([])
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
          const exists = prev.findIndex(
            s => s.type === data.step.type && s.message === data.step.message
          )
          if (exists >= 0) {
            const updated = [...prev]
            updated[exists] = data.step
            return updated
          }
          return [...prev.slice(-8), data.step]
        })
      }

      if (data.event === "wiki_updated") {
        axios.get(`${API}/api/wiki/pages`).then(({ data: d }) => setWikiPages(d.pages))
        if (data.sources) setSources(data.sources)
      }

      if (data.event === "answer_assessed") setGaps(data.gaps || [])
      if (data.event === "show_sources") setSources(data.sources || [])
      if (data.event === "source_removed") {
        setSources(prev => prev.filter(s => s.id !== data.source_id))
      }
      if (data.event === "file_uploaded") {
        setSources(prev => [...prev, data.source])
      }
    }

    return () => ws.close()
  }, [sessionId])

  const clearReasoning = () => setReasoning([])

  return {
    sessionId,
    sources,
    setSources,
    gaps,
    wikiPages,
    setWikiPages,
    reasoning,
    clearReasoning,
    wsRef
  }
}
