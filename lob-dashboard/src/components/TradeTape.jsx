import React, { useEffect, useRef } from 'react'

const fmt = p => '$' + (p / 100).toFixed(2)

function TradeRow({ trade }) {
  const time = new Date(trade.ts).toLocaleTimeString('en-US', { hour12: false })
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr 1fr 1fr',
      padding: '7px 16px',
      borderBottom: '1px solid var(--border)',
      fontFamily: 'var(--mono)',
      fontSize: 12,
      alignItems: 'center',
      animation: 'slideIn 0.18s ease',
    }}>
      <span style={{ color: 'var(--purple)', fontWeight: 500 }}>{fmt(trade.price)}</span>
      <span style={{ color: 'var(--text)', textAlign: 'center' }}>{trade.qty}</span>
      <span style={{ color: 'var(--muted)', textAlign: 'right', fontSize: 11 }}>{time}</span>
    </div>
  )
}

export default function TradeTape({ trades, tradeCount }) {
  const bodyRef = useRef(null)

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Trade Tape</span>
        <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>
          {tradeCount} execution{tradeCount !== 1 ? 's' : ''}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', padding: '7px 16px', fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.6px', background: 'var(--bg)', borderBottom: '1px solid var(--border)' }}>
        <span>Price</span>
        <span style={{ textAlign: 'center' }}>Qty</span>
        <span style={{ textAlign: 'right' }}>Time</span>
      </div>
      <div ref={bodyRef} style={{ height: 420, overflowY: 'auto', scrollbarWidth: 'thin' }}>
        {trades.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 200, color: 'var(--muted)', fontSize: 13, gap: 8 }}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.35">
              <path d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
            </svg>
            Waiting for trades...
          </div>
        ) : (
          trades.map(t => <TradeRow key={t.id + '-' + t.ts} trade={t} />)
        )}
      </div>
    </div>
  )
}
