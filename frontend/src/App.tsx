import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { RequireRole } from './auth/RequireRole'
import { Layout } from './components/Layout'
import { PublicLayout } from './components/marketing/PublicLayout'
import { PageSkeleton } from './components/PageSkeleton'
import { AboutPage } from './pages/AboutPage'
import { AssessmentPage } from './pages/AssessmentPage'
import { LandingPage } from './pages/LandingPage'
import { LoginPage } from './pages/LoginPage'
import { PatientHomePage } from './pages/PatientHomePage'
import { NotFoundPage } from './pages/PlaceholderPage'
import { SetupStatusPage } from './pages/SetupStatusPage'

const DoctorRoutes = lazy(() => import('./features/doctor/DoctorRoutes'))

/**
 * Landing → Sign in → role home. Public: `/`, `/about`, `/login`, `/status`. Protected deep links go
 * straight to `/login` with a validated return path (never through the landing page).
 */
export default function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route index element={<LandingPage />} />
        <Route path="about" element={<AboutPage />} />
      </Route>
      <Route path="login" element={<LoginPage />} />
      <Route element={<RequireRole role="doctor" />}>
        <Route
          path="doctor/*"
          element={
            <Suspense fallback={<PageSkeleton label="Loading dashboard…" />}>
              <DoctorRoutes />
            </Suspense>
          }
        />
      </Route>
      <Route element={<Layout />}>
        <Route path="status" element={<SetupStatusPage />} />
        <Route element={<RequireRole role="patient" />}>
          <Route path="patient" element={<PatientHomePage />} />
          <Route path="patient/check-in" element={<AssessmentPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
