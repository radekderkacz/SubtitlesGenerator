import { z } from 'zod'

export const schema = z.object({
  transcription_api_url: z.string(),
  transcription_model: z.string(),
  transcription_api_key: z.string(),
  translation_provider: z.string(),
  translation_model: z.string(),
  translation_api_key: z.string(),
  translation_api_url: z.string(),
})

export type FormValues = z.infer<typeof schema>
