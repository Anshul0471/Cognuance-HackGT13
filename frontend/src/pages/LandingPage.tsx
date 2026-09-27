import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { FeatureCards } from '../components/marketing/FeatureCards'
import { HowItWorks } from '../components/marketing/HowItWorks'
import { LandingHero } from '../components/marketing/LandingHero'
import { useDocumentTitle } from '../lib/useDocumentTitle'

/** Public welcome page. Loads without credentials and never requests patient records. */
export function LandingPage() {
  useDocumentTitle('Welcome')
  const { hash, key } = useLocation()

  // In-app links to "/#how-it-works" (e.g. from About) scroll to the section after navigation.
  useEffect(() => {
    if (!hash) return
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash, key])

  return (
    <>
      <LandingHero />
      <HowItWorks />
      <FeatureCards />
    </>
  )
}
