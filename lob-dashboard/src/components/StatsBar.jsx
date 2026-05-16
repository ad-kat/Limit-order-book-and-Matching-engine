import React from 'react'

const fmt = p => p != null ? '$' + (p / 100).toFixed(2) : '—'

export default function StatsBar({ bids, asks, tradeCount, connected }) {
  const bidPrices = Object.keys(bids).map(Number).sort((a, b) => b - a)
  const askPrices = Object.keys(asks).map(Number).sort((a, b) => a - b)
  const bestBid = bidPrices[0]
  const bestAsk = askPrices[0]
  const spread  = bestBid && bestAsk ? bestAsk - bestBid : null

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 12,
      marginBottom: 20,
    }}>
      {[
        { label: 'Best Bid',  value: fmt(bestBid),          color: 'var(--bid)'    },
        { label: 'Best Ask',  value: fmt(bestAsk),          color: 'var(--ask)'    },
        { label: 'Spread',    value: fmt(spread),           color: 'var(--purple)' },
        { label: 'Trades',    value: tradeCount.toString(), color: 'var(--text)'   },
      ].map(({ label, value, color }) => (
        <div key={label} style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          padding: '14px 16px',
        }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 6 }}>
            {label}
          </div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 20, fontWeight: 500, color }}>
            {value}
          </div>
        </div>
      ))}
    </div>
  )
}
