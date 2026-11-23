import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { AuthProvider } from './lib/auth.jsx'
import { FeedbackProvider } from './ui/index.jsx'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <FeedbackProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </FeedbackProvider>
  </React.StrictMode>,
)
