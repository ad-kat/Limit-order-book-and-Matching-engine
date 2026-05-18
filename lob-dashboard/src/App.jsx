import React from 'react'
import { useLOB } from './hooks/useLOB'
import StatsBar   from './components/StatsBar'
import OrderBook  from './components/OrderBook'
import TradeTape  from './components/TradeTape'

// Inline keyframe for trade row animation
const globalStyle = `
  @keyframes slideIn {
    from { opacity: 0; transform: translateX(6px); }
    to   { opacity: 1; transform: translateX(0);   }
  }
`

// Use build-time injected WS URL (set via VITE_API_URL env var)
const WS_URL = (typeof __WS_URL__ !== 'undefined' ? __WS_URL__ : null) || 'ws://localhost:8000/ws'
const WS_HOST = WS_URL.replace('wss://', '').replace('ws://', '').split('/')[0]

export default function App() {
  const { bids, asks, trades, tradeCount, connected } = useLOB(WS_URL)

  return (
    <>
      <style>{globalStyle}</style>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 20px' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {/* Logo */}
            <div style={{ width: 36, height: 36, background: 'var(--purple)', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <rect x="2"  y="10" width="3" height="8"  rx="1" fill="white"/>
                <rect x="7"  y="6"  width="3" height="12" rx="1" fill="white" opacity="0.8"/>
                <rect x="12" y="2"  width="3" height="16" rx="1" fill="white" opacity="0.6"/>
                <rect x="17" y="7"  width="3" height="11" rx="1" fill="white" opacity="0.4"/>
              </svg>
            </div>
            <span style={{ fontSize: 17, fontWeight: 600, letterSpacing: '-0.3px' }}>
              LOB <span style={{ color: 'var(--purple)' }}>Engine</span>
            </span>
            <span style={{
              background: 'var(--purple-lt)', color: 'var(--purple)',
              fontFamily: 'var(--mono)', fontSize: 12, fontWeight: 500,
              padding: '3px 10px', borderRadius: 20,
              border: '1px solid var(--purple-md)',
            }}>
              AAPL
            </span>
          </div>

          {/* Connection badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{
              width: 8, height: 8, borderRadius: '50%',
              background: connected ? '#10B981' : '#F59E0B',
              boxShadow: connected ? '0 0 0 3px #D1FAE5' : '0 0 0 3px #FEF3C7',
            }} />
            <span style={{ fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>
              {connected ? `live · ${WS_HOST}` : 'mock data'}
            </span>
          </div>
        </div>

        {/* Stats */}
        <StatsBar bids={bids} asks={asks} tradeCount={tradeCount} connected={connected} />

        {/* Main grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16 }}>
          <OrderBook bids={bids} asks={asks} />
          <TradeTape trades={trades} tradeCount={tradeCount} />
        </div>

      </div>
    </>
  )
}