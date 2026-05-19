import React, { useEffect, useState } from 'react'

export default function Commentary({ commentary }) {
  const [visible, setVisible] = useState(false)
  const [displayed, setDisplayed] = useState(null)

  useEffect(() => {
    if (!commentary) return
    setDisplayed(commentary)
    setVisible(true)
    const timer = setTimeout(() => setVisible(false), 12000) // fade after 12s
    return () => clearTimeout(timer)
  }, [commentary?.ts])

  if (!displayed) return null

  return (
    <div style={{
      margin: '12px 0',
      padding: '12px 16px',
      borderRadius: 10,
      background: 'var(--purple-lt)',
      border: '1px solid var(--purple-md)',
      display: 'flex',
      alignItems: 'flex-start',
      gap: 10,
      opacity: visible ? 1 : 0.3,
      transition: 'opacity 1.5s ease',
    }}>
      {/* AI badge */}
      <div style={{
        flexShrink: 0,
        background: 'var(--purple)',
        borderRadius: 6,
        padding: '2px 7px',
        fontSize: 10,
        fontWeight: 700,
        color: '#fff',
        letterSpacing: '0.5px',
        marginTop: 1,
        fontFamily: 'var(--mono)',
      }}>
        AI
      </div>

      {/* Commentary text */}
      <div style={{ flex: 1 }}>
        <span style={{
          fontSize: 13,
          color: 'var(--purple)',
          fontWeight: 500,
          lineHeight: 1.5,
        }}>
          {displayed.text}
        </span>
        <span style={{
          marginLeft: 8,
          fontSize: 11,
          color: 'var(--muted)',
          fontFamily: 'var(--mono)',
        }}>
          {displayed.symbol} · {displayed.event}
        </span>
      </div>

      {/* Gemini badge */}
      <div style={{
        flexShrink: 0,
        fontSize: 10,
        color: 'var(--muted)',
        fontFamily: 'var(--mono)',
        marginTop: 2,
        opacity: 0.6,
      }}>
        gemini-flash
      </div>
    </div>
  )
}
