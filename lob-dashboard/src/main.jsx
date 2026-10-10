import React from 'react'
import ReactDOM from 'react-dom/client'
import FairSplitApp from './FairSplitApp'
import './index.css'

// FairSplit is the default view.
// The original LOB dashboard (App.jsx) is preserved but not shown by default.
// To restore it: import App from './App' and render <App /> instead.
ReactDOM.createRoot(document.getElementById('root')).render(<FairSplitApp />)
