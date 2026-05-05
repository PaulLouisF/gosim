import { useEffect, useRef } from "react"

const SCORE_COLORS = {
  strong: "text-green-400",
  partial: "text-yellow-400",
  missed: "text-red-400"
}

export default function ConversationFeed({ messages }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  return (
    <div className="space-y-4">
      {messages.map(msg => (
        <div key={msg.id} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}>
          {msg.role === "agent" && (
            <div className="w-6 h-6 rounded bg-violet-600 flex items-center
                           justify-center text-xs flex-shrink-0 mt-1">S</div>
          )}
          <div className={`max-w-lg rounded-xl px-4 py-3 text-sm leading-relaxed
                          ${msg.role === "user"
                            ? "bg-white/8 border border-white/10 text-white/90"
                            : "bg-violet-500/8 border border-violet-500/15 text-white/85"}`}>
            {msg.text}
            {msg.data?.score && (
              <div className={`text-xs mt-1 font-semibold ${SCORE_COLORS[msg.data.score]}`}>
                {msg.data.score === "strong" ? "✓ Correct" :
                 msg.data.score === "partial" ? "~ Partial" : "✗ Missed"}
              </div>
            )}
            <div className="text-white/20 text-xs mt-1">{msg.timestamp}</div>
          </div>
          {msg.role === "user" && (
            <div className="w-6 h-6 rounded bg-white/10 flex items-center
                           justify-center text-xs flex-shrink-0 mt-1">U</div>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
