import { useRef, useState } from "react"
import axios from "axios"

const API = "http://localhost:8000"

export default function UploadZone({ sessionId, onUploaded }) {
  const [uploading, setUploading] = useState(false)
  const [uploaded, setUploaded] = useState(null)
  const inputRef = useRef(null)

  const handleFile = async (file) => {
    setUploading(true)
    const form = new FormData()
    form.append("file", file)
    try {
      const { data } = await axios.post(
        `${API}/api/session/${sessionId}/upload`,
        form
      )
      setUploaded(data.source)
      setTimeout(onUploaded, 1500)
    } catch (err) {
      console.error(err)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="absolute top-0 right-0 w-80 bg-[#0d0d14] border-l
                   border-white/10 z-10 p-6 space-y-4">
      <div className="font-bold text-sm">Upload Document</div>

      {uploaded ? (
        <div className="text-green-400 text-sm">
          ✓ {uploaded.title} uploaded
        </div>
      ) : (
        <div
          className="border-2 border-dashed border-white/15 rounded-xl p-8
                     text-center cursor-pointer hover:border-violet-500/50 transition-all"
          onClick={() => inputRef.current?.click()}
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            e.preventDefault()
            const f = e.dataTransfer.files[0]
            if (f) handleFile(f)
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.txt,.md,.docx"
            className="hidden"
            onChange={e => e.target.files[0] && handleFile(e.target.files[0])}
          />
          {uploading ? (
            <div className="text-violet-400 animate-pulse text-sm">Uploading...</div>
          ) : (
            <>
              <div className="text-2xl mb-2">📄</div>
              <div className="text-sm text-white/40">
                Drop a file or click to browse
              </div>
              <div className="text-xs text-white/20 mt-1">
                PDF, TXT, MD, DOCX
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
