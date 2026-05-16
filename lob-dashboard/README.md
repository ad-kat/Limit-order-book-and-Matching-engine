# LOB Dashboard

React + Vite dashboard for the Limit Order Book engine.

## Run locally

```bash
npm install
npm run dev
```

Open http://localhost:5173

Connects to the LOB API at `ws://localhost:8000/ws` automatically.
Falls back to mock data if the API is not running — so the dashboard
always shows something useful.

## Deploy to Vercel

```bash
npm install -g vercel
vercel
```

## Build for production

```bash
npm run build   # outputs to dist/
```
