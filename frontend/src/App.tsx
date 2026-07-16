import { Routes, Route } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { AnalysisPage } from './pages/AnalysisPage'
import { ActivitiesPage } from './pages/ActivitiesPage'
import { ActivityDetailPage } from './pages/ActivityDetailPage'
import { HealthPage } from './health/HealthPage'
import { ConnectorsPage } from './connectors/ConnectorsPage'
import { SettingsPage } from './settings/SettingsPage'
import { RequireAuth } from './auth/RequireAuth'
import './App.css'

export function App() {
  return (
    <Routes>
      {/* Standalone login page — no top-nav chrome (C-2). */}
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<AnalysisPage />} />
          <Route path="/activities" element={<ActivitiesPage />} />
          <Route path="/activities/:id" element={<ActivityDetailPage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route path="/connectors" element={<ConnectorsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
