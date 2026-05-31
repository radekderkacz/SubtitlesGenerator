import type { Settings } from '@/types/api'

export const baseMockSettings: Settings = {
  id: 1,
  nas_mount_path: '/mnt/nas',
  watch_folders: [],
  jellyfin_url: null,
  jellyfin_api_key: null,
  transcription_api_url: null,
  transcription_model: null,
  transcription_api_key: null,
  translation_provider: null,
  translation_model: null,
  translation_api_key: null,
  translation_api_url: null,
  hf_token: null,
  profiles: [],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}
