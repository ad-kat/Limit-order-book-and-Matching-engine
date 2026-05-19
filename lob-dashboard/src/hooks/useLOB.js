import { useState, useEffect, useRef } from 'react'

const WS_URL = (typeof __WS_URL__ !== 'undefined' ? __WS_URL__ : null) || 'ws://localhost:8000/ws'

let mid = 29900
let mockOrderId = 1

function mockTick(setState) {
  mid += Math.round((Math.random() - 0.49) * 8)
  mid = Math.max(29500, Math.min(30500, mid))

  const spread = 5 + Math.floor(Math.random() * 10)
  const bid = mid - Math.floor(spread / 2)
  const ask = mid + Math.ceil(spread / 2)

  const bids = {}
  const asks = {}
  for (let i = 0; i < 8; i++) {
    bids[bid - i * (3 + Math.floor(Math.random() * 5))] = 1 + Math.floor(Math.random() * 40)
    asks[ask + i * (3 + Math.floor(Math.random() * 5))] = 1 + Math.floor(Math.random() * 40)
  }

  const hasTrade = Math.random() < 0.4
  const trade = hasTrade ? {
    price: Math.random() < 0.5 ? bid : ask,
    qty:   1 + Math.floor(Math.random() * 25),
    id:    mockOrderId++,
    ts:    Date.now(),
  } : null

  setState(prev => ({
    ...prev,
    bids,
    asks,
    trades:     trade ? [trade, ...prev.trades].slice(0, 100) : prev.trades,
    tradeCount: trade ? prev.tradeCount + 1 : prev.tradeCount,
  }))
}

export function useLOB(wsUrl = WS_URL) {
  const [state, setState] = useState({
    bids: {}, asks: {}, trades: [], tradeCount: 0, connected: false,
    commentary: null,  // { symbol, text, event, ts }
  })
  const mockTimer = useRef(null)
  const wsRef     = useRef(null)

  useEffect(() => {
    mockTimer.current = setInterval(() => mockTick(setState), 650)

    function connect() {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        clearInterval(mockTimer.current)
        mockTimer.current = null
        setState(p => ({ ...p, connected: true }))
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.event === 'trade') {
            const t = { ...msg.payload, id: msg.payload.buy_id, ts: Date.now() }
            setState(p => ({
              ...p,
              trades:     [t, ...p.trades].slice(0, 100),
              tradeCount: p.tradeCount + 1,
            }))
          }
          if (msg.event === 'book') {
            const { best_bid, best_ask } = msg.payload
            setState(p => ({
              ...p,
              bids: best_bid ? { ...p.bids, [best_bid]: (p.bids[best_bid] || 0) + 1 } : p.bids,
              asks: best_ask ? { ...p.asks, [best_ask]: (p.asks[best_ask] || 0) + 1 } : p.asks,
            }))
          }
          if (msg.event === 'commentary') {
            setState(p => ({
              ...p,
              commentary: { ...msg.payload, ts: Date.now() },
            }))
          }
        } catch (_) {}
      }

      ws.onerror  = () => {}
      ws.onclose  = () => {
        setState(p => ({ ...p, connected: false }))
        if (!mockTimer.current) {
          mockTimer.current = setInterval(() => mockTick(setState), 650)
        }
        setTimeout(connect, 3000)
      }
    }

    const t = setTimeout(connect, 800)

    return () => {
      clearTimeout(t)
      clearInterval(mockTimer.current)
      wsRef.current?.close()
    }
  }, [wsUrl])

  return state
}
