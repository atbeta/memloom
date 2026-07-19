import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthGate } from '@/components/AuthGate'
import { Shell } from '@/components/Shell'
import Overview from '@/pages/Overview'
import Explorer from '@/pages/Explorer'
import Pipeline from '@/pages/Pipeline'
import Settings from '@/pages/Settings'

export default function App() {
  return (
    <BrowserRouter>
      <AuthGate>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<Overview />} />
            <Route path="explorer" element={<Explorer />} />
            <Route path="pipeline" element={<Pipeline />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthGate>
    </BrowserRouter>
  )
}
