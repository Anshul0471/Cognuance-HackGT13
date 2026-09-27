import { Route, Routes } from 'react-router-dom'
import { NotFoundPage } from '../../pages/PlaceholderPage'
import { DoctorLayout } from './components/DoctorLayout'
import { AlertDetailPage } from './pages/AlertDetailPage'
import { AlertListPage } from './pages/AlertListPage'
import { AssessmentDetailPage } from './pages/AssessmentDetailPage'
import { DoctorOverviewPage } from './pages/DoctorOverviewPage'
import { PatientDetailPage } from './pages/PatientDetailPage'
import { PatientListPage } from './pages/PatientListPage'
import { VisualInsightsPage } from './pages/VisualInsightsPage'

/**
 * The doctor area, loaded as its own chunk (Recharts and the dashboard stay out of the public
 * bundle). Mounted under `/doctor/*` behind `RequireRole role="doctor"`.
 */
export default function DoctorRoutes() {
  return (
    <Routes>
      <Route element={<DoctorLayout />}>
        <Route index element={<DoctorOverviewPage />} />
        <Route path="patients" element={<PatientListPage />} />
        <Route path="patients/:patientId" element={<PatientDetailPage />} />
        <Route path="patients/:patientId/assessments/:assessmentId" element={<AssessmentDetailPage />} />
        <Route path="insights" element={<VisualInsightsPage />} />
        <Route path="alerts" element={<AlertListPage />} />
        <Route path="alerts/:alertId" element={<AlertDetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
