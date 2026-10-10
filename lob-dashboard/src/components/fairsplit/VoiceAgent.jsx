import React, { useCallback, useEffect, useRef, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_BASE = API_BASE.replace(/^http/, 'ws')

const STATUS_LABELS = {
  disconnected: 'Disconnected',
  connecting:   'Connecting…',
  connected:    'Connected',
  listening:    'Listening…',
  speaking:     'Speaking…',
  idle:         'Idle',
  error:        'Error',
}

function ToolActivity({ activity }) {
  if (!activity || activity.length === 0) return null
  return (
    <div className="tool-activity">
      <div className="tool-activity__title">Agent Activity</div>
      {activity.map((item, i) => (
        <div key={i} className="tool-item">
          <span className="tool-item__name">{item.tool}</span>
          <span className="tool-item__arrow">→</span>
          <span className="tool-item__result">
            {typeof item.result === 'object'
              ? JSON.stringify(item.result).slice(0, 80) + '…'
              : String(item.result)}
          </span>
        </div>
      ))}
    </div>
  )
}

function TranscriptBubble({ entry }) {
  const isUser = entry.role === 'user'
  return (
    <div className={`transcript-bubble transcript-bubble--${isUser ? 'user' : 'model'}`}>
      <span className="transcript-bubble__role">{isUser ? 'You' : 'FairSplit'}</span>
      <span className="transcript-bubble__text">{entry.text}</span>
    </div>
  )
}

export default function VoiceAgent() {
  const [status, setStatus] = useState('disconnected')
  const [transcript, setTranscript] = useState([])
  const [toolActivity, setToolActivity] = useState([])
  const [error, setError] = useState('')
  const [textInput, setTextInput] = useState('')
  const [recording, setRecording] = useState(false)

  const wsRef            = useRef(null)
  const mediaRecorderRef = useRef(null)
  const audioCtxRef      = useRef(null)
  const transcriptEndRef = useRef(null)

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcript])

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState < 2) return
    setStatus('connecting')
    setError('')
    const ws = new WebSocket(`${WS_BASE}/fairsplit/agent`)
    wsRef.current = ws

    ws.onopen = () => setStatus('connected')

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        if (msg.type === 'status') {
          setStatus(msg.status)
        } else if (msg.type === 'transcript') {
          setTranscript(prev => [...prev, { role: msg.role, text: msg.text }])
        } else if (msg.type === 'tool_call') {
          setToolActivity(prev => [...prev.slice(-9), {
            tool: msg.tool,
            args: msg.args,
            result: msg.result,
          }])
        } else if (msg.type === 'audio') {
          playAudio(msg.data)
        } else if (msg.type === 'error') {
          setError(msg.message)
          if (msg.message.includes('GEMINI_API_KEY')) {
            // still allow text mode
            setStatus('connected')
          } else {
            setStatus('error')
          }
        }
      } catch (e) {
        // non-JSON
      }
    }

    ws.onerror = () => {
      setStatus('error')
      setError('WebSocket connection failed. Is the API server running?')
    }

    ws.onclose = () => {
      if (status !== 'error') setStatus('disconnected')
    }
  }, [status])

  const disconnect = useCallback(() => {
    wsRef.current?.close()
    stopRecording()
    setStatus('disconnected')
  }, [])

  function playAudio(base64Data) {
    try {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new AudioContext()
      }
      const ctx = audioCtxRef.current
      const binary = atob(base64Data)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
      ctx.decodeAudioData(bytes.buffer, (buf) => {
        const src = ctx.createBufferSource()
        src.buffer = buf
        src.connect(ctx.destination)
        src.start(0)
        setStatus('speaking')
        src.onended = () => setStatus('idle')
      })
    } catch (e) {
      // audio playback not critical
    }
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      mediaRecorderRef.current = mr

      mr.ondataavailable = (evt) => {
        if (evt.data.size > 0 && wsRef.current?.readyState === 1) {
          const reader = new FileReader()
          reader.onload = () => {
            const base64 = reader.result.split(',')[1]
            wsRef.current.send(base64)
          }
          reader.readAsDataURL(evt.data)
        }
      }

      mr.start(250) // chunk every 250ms
      setRecording(true)
      setStatus('listening')
    } catch (e) {
      setError('Microphone access denied: ' + e.message)
    }
  }

  function stopRecording() {
    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.stop()
      mediaRecorderRef.current.stream?.getTracks().forEach(t => t.stop())
      mediaRecorderRef.current = null
    }
    setRecording(false)
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ type: 'end_audio' }))
    }
    setStatus('idle')
  }

  function sendText() {
    const text = textInput.trim()
    if (!text || wsRef.current?.readyState !== 1) return
    wsRef.current.send(JSON.stringify({ type: 'text', text }))
    setTextInput('')
    setStatus('idle')
  }

  const connected = status !== 'disconnected' && status !== 'error'

  return (
    <div className="voice-agent">
      <div className="voice-agent__sidebar">
        <div className={`agent-status agent-status--${status}`}>
          <span className="agent-status__dot" />
          {STATUS_LABELS[status] || status}
        </div>

        {error && (
          <div className="agent-error">{error}</div>
        )}

        <div className="agent-controls">
          {!connected ? (
            <button className="btn btn--primary" onClick={connect}>Connect</button>
          ) : (
            <button className="btn btn--outline" onClick={disconnect}>Disconnect</button>
          )}

          {connected && (
            <button
              className={`btn btn--mic${recording ? ' btn--mic--active' : ''}`}
              onClick={recording ? stopRecording : startRecording}
            >
              {recording ? 'Stop Recording' : 'Start Microphone'}
            </button>
          )}
        </div>

        <ToolActivity activity={toolActivity} />
      </div>

      <div className="voice-agent__main">
        <div className="transcript">
          {transcript.length === 0 && (
            <div className="transcript-empty">
              {connected
                ? 'Say something or type a message below…'
                : 'Connect to start a conversation with FairSplit AI.'}
            </div>
          )}
          {transcript.map((entry, i) => (
            <TranscriptBubble key={i} entry={entry} />
          ))}
          <div ref={transcriptEndRef} />
        </div>

        <div className="agent-text-input">
          <input
            type="text"
            className="agent-text-input__field"
            placeholder={connected ? 'Type a message…' : 'Connect first…'}
            value={textInput}
            disabled={!connected}
            onChange={e => setTextInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendText()}
          />
          <button
            className="btn btn--primary"
            onClick={sendText}
            disabled={!connected || !textInput.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
