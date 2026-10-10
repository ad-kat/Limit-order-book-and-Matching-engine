import React, { useCallback, useEffect, useRef, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_BASE  = API_BASE.replace(/^https?/, m => m === 'https' ? 'wss' : 'ws')

// Gemini Live expects PCM 16-bit LE at 16 kHz mono.
// Gemini Live emits  PCM 16-bit LE at 24 kHz mono.
const CAPTURE_SAMPLE_RATE  = 16000
const PLAYBACK_SAMPLE_RATE = 24000
const CHUNK_MS = 100   // how often to flush capture buffer

const STATUS_LABELS = {
  disconnected: 'Disconnected',
  connecting:   'Connecting…',
  connected:    'Connected',
  listening:    'Listening…',
  speaking:     'Speaking…',
  idle:         'Idle',
  error:        'Error',
}

// ── AudioWorklet processor inline (avoids separate file) ──────────────────────
const WORKLET_SRC = `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = [];
    this._target = ${CAPTURE_SAMPLE_RATE};
    this._ratio = sampleRate / this._target;
    this._pos = 0;
  }
  process(inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;
    // Downsample by picking every ratio-th sample
    for (let i = 0; i < ch.length; i++) {
      this._pos += 1;
      if (this._pos >= this._ratio) {
        this._pos -= this._ratio;
        // Convert float32 → int16
        const s = Math.max(-1, Math.min(1, ch[i]));
        this._buf.push(s < 0 ? s * 0x8000 : s * 0x7FFF);
      }
    }
    // Flush ~every CHUNK_MS
    const chunkSamples = Math.floor(this._target * ${CHUNK_MS} / 1000);
    if (this._buf.length >= chunkSamples) {
      const out = new Int16Array(this._buf.splice(0, chunkSamples));
      this.port.postMessage(out.buffer, [out.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-capture', PcmCaptureProcessor);
`

function ToolActivity({ activity }) {
  if (!activity.length) return null
  return (
    <div className="tool-activity">
      <div className="tool-activity__title">Agent Activity</div>
      {activity.map((item, i) => (
        <div key={i} className="tool-item">
          <span className="tool-item__name">{item.tool}</span>
          <span className="tool-item__arrow">→</span>
          <span className="tool-item__result">
            {typeof item.result === 'object'
              ? JSON.stringify(item.result).slice(0, 100)
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

// ── Raw PCM playback ──────────────────────────────────────────────────────────
// Gemini sends PCM 16-bit LE at 24 kHz. decodeAudioData() can't handle raw PCM;
// we must build an AudioBuffer manually.
function playPcm16(base64Data, audioCtx, onEnd) {
  try {
    const binary  = atob(base64Data)
    const bytes   = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)

    const samples = bytes.length / 2
    const buf     = audioCtx.createBuffer(1, samples, PLAYBACK_SAMPLE_RATE)
    const ch      = buf.getChannelData(0)
    const view    = new DataView(bytes.buffer)
    for (let i = 0; i < samples; i++) {
      // Read int16 LE, convert to float32 [-1, 1]
      ch[i] = view.getInt16(i * 2, true) / 32768.0
    }
    const src = audioCtx.createBufferSource()
    src.buffer = buf
    src.connect(audioCtx.destination)
    src.start(0)
    src.onended = onEnd
  } catch (e) {
    // Audio playback failure is non-fatal
    console.warn('[FairSplit] PCM playback error:', e)
    onEnd?.()
  }
}

// ── Main component ────────────────────────────────────────────────────────────
export default function VoiceAgent() {
  const [status,       setStatus]       = useState('disconnected')
  const [transcript,   setTranscript]   = useState([])  // [{role, text}]
  const [toolActivity, setToolActivity] = useState([])
  const [error,        setError]        = useState('')
  const [textInput,    setTextInput]    = useState('')
  const [recording,    setRecording]    = useState(false)

  const wsRef           = useRef(null)
  const audioCtxRef     = useRef(null)
  const workletNodeRef  = useRef(null)
  const streamRef       = useRef(null)
  const transcriptEndRef = useRef(null)
  // For accumulating streaming transcript tokens into one bubble per turn
  const lastRoleRef     = useRef(null)

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcript])

  // Accumulate streaming transcript tokens: append to last bubble if same role
  const addTranscript = useCallback((role, text) => {
    setTranscript(prev => {
      if (prev.length > 0 && prev[prev.length - 1].role === role) {
        const updated = [...prev]
        updated[updated.length - 1] = { role, text: updated[updated.length - 1].text + text }
        return updated
      }
      return [...prev, { role, text }]
    })
    lastRoleRef.current = role
  }, [])

  const ensureAudioCtx = () => {
    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new AudioContext()
    }
    if (audioCtxRef.current.state === 'suspended') {
      audioCtxRef.current.resume()
    }
    return audioCtxRef.current
  }

  const connect = useCallback(() => {
    if (wsRef.current?.readyState < 2) return
    setStatus('connecting')
    setError('')
    setTranscript([])
    setToolActivity([])
    lastRoleRef.current = null

    const ws = new WebSocket(`${WS_BASE}/fairsplit/agent`)
    wsRef.current = ws

    ws.onopen = () => {}   // status set by server's first message

    ws.onmessage = (evt) => {
      let msg
      try { msg = JSON.parse(evt.data) } catch { return }

      switch (msg.type) {
        case 'status':
          setStatus(msg.status)
          break
        case 'transcript':
          addTranscript(msg.role, msg.text)
          break
        case 'tool_call':
          setToolActivity(prev => [...prev.slice(-9), {
            tool: msg.tool, args: msg.args, result: msg.result,
          }])
          break
        case 'audio': {
          const ctx = ensureAudioCtx()
          setStatus('speaking')
          playPcm16(msg.data, ctx, () => setStatus('idle'))
          break
        }
        case 'error':
          setError(msg.message)
          // GEMINI_API_KEY missing → degrade to text mode, keep connected
          if (msg.message.includes('GEMINI_API_KEY')) {
            setStatus('connected')
          } else {
            setStatus('error')
          }
          break
      }
    }

    ws.onerror = () => {
      setStatus('error')
      setError('WebSocket failed. Is the API server running on ' + API_BASE + '?')
    }

    ws.onclose = (evt) => {
      if (evt.code !== 1000) setStatus('disconnected')
      stopRecording()
    }
  }, [addTranscript])

  const disconnect = useCallback(() => {
    stopRecording()
    wsRef.current?.close(1000, 'user disconnect')
    setStatus('disconnected')
  }, [])

  // ── PCM capture via AudioWorklet ──────────────────────────────────────────
  async function startRecording() {
    try {
      const ctx    = ensureAudioCtx()
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      streamRef.current = stream

      // Register worklet from a blob URL (no separate file needed)
      const blob    = new Blob([WORKLET_SRC], { type: 'application/javascript' })
      const blobUrl = URL.createObjectURL(blob)
      await ctx.audioWorklet.addModule(blobUrl)
      URL.revokeObjectURL(blobUrl)

      const source = ctx.createMediaStreamSource(stream)
      const node   = new AudioWorkletNode(ctx, 'pcm-capture')
      workletNodeRef.current = node

      node.port.onmessage = (e) => {
        if (wsRef.current?.readyState !== 1) return
        // Send as base64-encoded PCM chunk
        const pcm16    = new Int16Array(e.data)
        const bytes    = new Uint8Array(pcm16.buffer)
        let binary     = ''
        for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
        const b64      = btoa(binary)
        wsRef.current.send(JSON.stringify({ type: 'audio_chunk', data: b64 }))
      }

      source.connect(node)
      node.connect(ctx.destination)   // needed to keep graph alive (silent output)

      setRecording(true)
      setStatus('listening')
    } catch (e) {
      setError('Microphone error: ' + e.message)
    }
  }

  function stopRecording() {
    workletNodeRef.current?.disconnect()
    workletNodeRef.current = null
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
    setRecording(false)
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ type: 'end_audio' }))
    }
    if (status === 'listening') setStatus('idle')
  }

  function sendText() {
    const text = textInput.trim()
    if (!text || wsRef.current?.readyState !== 1) return
    wsRef.current.send(JSON.stringify({ type: 'text', text }))
    setTextInput('')
  }

  const connected = status !== 'disconnected' && status !== 'connecting' && status !== 'error'

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
          {status === 'disconnected' || status === 'error' ? (
            <button className="btn btn--primary" onClick={connect}>Connect</button>
          ) : (
            <button className="btn btn--outline" onClick={disconnect}>Disconnect</button>
          )}

          {connected && (
            <button
              className={`btn btn--mic${recording ? ' btn--mic--active' : ''}`}
              onClick={recording ? stopRecording : startRecording}
            >
              {recording ? '⏹ Stop' : '🎤 Speak'}
            </button>
          )}
        </div>

        <div className="agent-hint">
          <p>Try saying:</p>
          <ul>
            <li>"Find 3-bedroom apartments in Brooklyn"</li>
            <li>"My budget is $1,300. Find me roommates."</li>
            <li>"Find roommates for the Park Slope apartment"</li>
          </ul>
        </div>

        <ToolActivity activity={toolActivity} />
      </div>

      <div className="voice-agent__main">
        <div className="transcript">
          {transcript.length === 0 && (
            <div className="transcript-empty">
              {connected
                ? 'Say something or type below…'
                : 'Click Connect to start a voice session with FairSplit AI.'}
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
            placeholder={connected ? 'Or type a message…' : 'Connect first…'}
            value={textInput}
            disabled={!connected}
            onChange={e => setTextInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendText()}
          />
          <button
            className="btn btn--primary"
            onClick={sendText}
            disabled={!connected || !textInput.trim()}
          >Send</button>
        </div>
      </div>
    </div>
  )
}
