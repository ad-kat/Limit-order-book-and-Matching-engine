import React from 'react'

const fmt = p => '$' + (p / 100).toFixed(2)

function BookRow({ price, qty, side, maxQty }) {
  const pct  = ((qty / maxQty) * 100).toFixed(1)
  const total = ((price * qty) / 100).toFixed(0)
  const barColor = side === 'bid' ? 'var(--bid)' : 'var(--ask)'
  const priceColor = side === 'bid' ? 'var(--bid)' : 'var(--ask)'

  return (
    <tr style={{ position: 'relative' }}>
      {/* depth bar behind row */}
      <td colSpan={3} style={{ padding: 0, position: 'absolute', inset: 0, zIndex: 0 }}>
        <div style={{
          position: 'absolute', top: 0, right: 0, height: '100%',
          width: pct + '%', background: barColor, opacity: 0.08,
          transition: 'width 0.3s ease',
        }} />
      </td>
      <td style={{ fontFamily: 'var(--mono)', fontSize: 13, padding: '5px 16px', color: priceColor, fontWeight: 500, position: 'relative', zIndex: 1 }}>
        {fmt(price)}
      </td>
      <td style={{ fontFamily: 'var(--mono)', fontSize: 13, padding: '5px 16px', textAlign: 'right', color: 'var(--text)', position: 'relative', zIndex: 1 }}>
        {qty}
      </td>
      <td style={{ fontFamily: 'var(--mono)', fontSize: 13, padding: '5px 16px', textAlign: 'right', color: 'var(--muted)', position: 'relative', zIndex: 1 }}>
        {Number(total).toLocaleString()}
      </td>
    </tr>
  )
}

export default function OrderBook({ bids, asks }) {
  const bidLevels = Object.entries(bids).map(([p, q]) => [Number(p), q]).sort((a, b) => b[0] - a[0]).slice(0, 8)
  const askLevels = Object.entries(asks).map(([p, q]) => [Number(p), q]).sort((a, b) => a[0] - b[0]).slice(0, 8)

  const bestBid = bidLevels[0]?.[0]
  const bestAsk = askLevels[0]?.[0]
  const spread  = bestBid && bestAsk ? fmt(bestAsk - bestBid) : '—'

  const maxQty = Math.max(...bidLevels.map(([,q])=>q), ...askLevels.map(([,q])=>q), 1)

  const thStyle = {
    fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase',
    letterSpacing: '0.6px', fontWeight: 500, padding: '8px 16px',
    background: 'var(--bg)', borderBottom: '1px solid var(--border)',
  }

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Order Book</span>
        <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>price-time priority · FIFO</span>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ ...thStyle, textAlign: 'left' }}>Price</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Qty</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {askLevels.slice().reverse().map(([price, qty]) => (
            <BookRow key={price} price={price} qty={qty} side="ask" maxQty={maxQty} />
          ))}
          <tr>
            <td colSpan={3} style={{
              textAlign: 'center', padding: '6px',
              fontFamily: 'var(--mono)', fontSize: 11,
              color: 'var(--purple)', fontWeight: 500,
              background: 'var(--purple-lt)',
              borderTop: '1px solid var(--border)',
              borderBottom: '1px solid var(--border)',
            }}>
              spread &nbsp; {spread}
            </td>
          </tr>
          {bidLevels.map(([price, qty]) => (
            <BookRow key={price} price={price} qty={qty} side="bid" maxQty={maxQty} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
