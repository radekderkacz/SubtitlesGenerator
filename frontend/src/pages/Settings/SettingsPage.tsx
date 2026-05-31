import { useParams, Navigate } from 'react-router'
import SettingsLayout from './SettingsLayout'
import { isSectionId } from './sections'
export default function SettingsPage() {
  const { section } = useParams()
  if (!isSectionId(section)) return <Navigate to="/settings/media" replace />
  return <SettingsLayout section={section} />
}
