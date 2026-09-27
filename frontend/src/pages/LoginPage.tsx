import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowLeft, Eye, EyeOff, LogIn } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { safeReturnPath, useAuth } from '../auth/context'
import { BrandLogo } from '../components/brand/BrandLogo'
import { BRAND } from '../config/brand'
import { ApiError } from '../lib/api'
import { useDocumentTitle } from '../lib/useDocumentTitle'

const loginSchema = z.object({
  email: z.email('Enter a valid email address'),
  password: z.string().min(1, 'Enter your password'),
})

type LoginValues = z.infer<typeof loginSchema>

const inputClass =
  'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-lg transition-colors duration-150 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 aria-[invalid=true]:border-rose-400 motion-reduce:transition-none'

function rateLimitText(error: ApiError): string {
  const seconds = error.retryAfterSeconds
  if (!seconds) return 'Too many sign-in attempts. Try again in a few minutes.'
  const wait = seconds >= 90 ? `${Math.ceil(seconds / 60)} minutes` : `${seconds} seconds`
  return `Too many sign-in attempts. Try again in ${wait}.`
}

export function LoginPage() {
  useDocumentTitle('Sign in')
  const { user, login, lastSignOut } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [formError, setFormError] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const {
    register,
    handleSubmit,
    setFocus,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) })

  const from = (location.state as { from?: unknown } | null)?.from
  if (user) return <Navigate to={safeReturnPath(from, user.role)} replace />
  const signedOut = lastSignOut && (lastSignOut.revocationConfirmed ? 'confirmed' : 'unconfirmed')

  const onSubmit = async (values: LoginValues) => {
    setFormError(null)
    try {
      const signedIn = await login(values.email, values.password)
      navigate(safeReturnPath(from, signedIn.role), { replace: true })
    } catch (error) {
      // The email stays filled in; focus returns to the password so the user can simply retype it.
      if (error instanceof ApiError && error.status === 401) {
        setFormError('Incorrect email or password.')
        setFocus('password', { shouldSelect: true })
      } else if (error instanceof ApiError && error.status === 429) {
        setFormError(rateLimitText(error))
      } else if (error instanceof ApiError && error.isNetworkError) {
        setFormError('Could not reach the server. Try again shortly.')
      } else {
        setFormError('Sign-in failed. Try again.')
      }
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center bg-gradient-to-b from-indigo-50/70 via-slate-50 to-slate-50 px-4 py-10 text-slate-900">
      <BrandLogo to="/" />
      <main className="mt-8 w-full max-w-md">
        <div className="surface-card p-6 sm:p-8">
          <h1 className="text-2xl font-bold tracking-tight">Welcome back</h1>
          <p className="mt-1 text-slate-600">Sign in to continue to {BRAND.name}.</p>

          {signedOut === 'confirmed' && (
            <p role="status" className="mt-4 rounded-md bg-slate-100 px-3 py-2 text-sm text-slate-800">
              You have signed out.
            </p>
          )}
          {signedOut === 'unconfirmed' && (
            <p role="status" className="mt-4 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-950">
              You were signed out on this device, but the server could not confirm that the session was revoked. The
              server session still ends when its sign-in period expires.
            </p>
          )}

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-5">
            <div>
              <label htmlFor="email" className="block text-base font-medium">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                aria-invalid={errors.email ? 'true' : 'false'}
                aria-describedby={errors.email ? 'email-error' : undefined}
                className={inputClass}
                {...register('email')}
              />
              {errors.email && (
                <p id="email-error" className="mt-1 text-sm text-rose-700">
                  {errors.email.message}
                </p>
              )}
            </div>

            <div>
              <label htmlFor="password" className="block text-base font-medium">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  aria-invalid={errors.password ? 'true' : 'false'}
                  aria-describedby={errors.password ? 'password-error' : undefined}
                  className={`${inputClass} pr-12`}
                  {...register('password')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-pressed={showPassword}
                  aria-controls="password"
                  className="absolute top-1 right-1 mt-1 inline-flex h-10 w-10 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                >
                  {showPassword ? <EyeOff aria-hidden="true" className="h-5 w-5" /> : <Eye aria-hidden="true" className="h-5 w-5" />}
                  <span className="sr-only">{showPassword ? 'Hide password' : 'Show password'}</span>
                </button>
              </div>
              {errors.password && (
                <p id="password-error" className="mt-1 text-sm text-rose-700">
                  {errors.password.message}
                </p>
              )}
            </div>

            {formError && (
              <p role="alert" className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
                {formError}
              </p>
            )}

            <button type="submit" disabled={isSubmitting} className="btn-primary w-full py-3 text-lg">
              <LogIn aria-hidden="true" className="h-5 w-5" />
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <p className="mt-5 text-sm text-slate-500">Signing out or reloading the page ends your session.</p>
        </div>

        <nav aria-label="Sign-in page" className="mt-6 flex flex-wrap items-center justify-between gap-3 text-sm">
          <Link to="/" className="inline-flex min-h-11 items-center gap-1 font-medium text-indigo-800 underline-offset-4 hover:underline">
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            Back to home
          </Link>
          <Link to="/about" className="inline-flex min-h-11 items-center text-slate-600 underline-offset-4 hover:underline">
            About {BRAND.name}
          </Link>
        </nav>
      </main>
    </div>
  )
}
