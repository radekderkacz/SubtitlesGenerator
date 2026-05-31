import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import TestModelButton from './TestModelButton'

vi.mock('@/lib/api', () => ({
  testTranslationModel: vi.fn(),
  ApiRequestError: class ApiRequestError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.name = 'ApiRequestError'
      this.status = status
      this.code = code
    }
  },
}))

describe('TestModelButton', () => {
  beforeEach(async () => {
    const { testTranslationModel } = await import('@/lib/api')
    vi.mocked(testTranslationModel).mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('disables the button until provider + model are filled', () => {
    const { rerender } = render(
      <TestModelButton provider="" url="" model="" apiKey="" />,
    )
    expect(screen.getByRole('button', { name: /Test this model/i })).toBeDisabled()

    rerender(
      <TestModelButton provider="ollama" url="" model="" apiKey="" />,
    )
    expect(screen.getByRole('button', { name: /Test this model/i })).toBeDisabled()

    rerender(
      <TestModelButton provider="ollama" url="" model="gemma3:27b" apiKey="" />,
    )
    expect(screen.getByRole('button', { name: /Test this model/i })).not.toBeDisabled()
  })

  it('passes the current form values into the API call', async () => {
    const { testTranslationModel } = await import('@/lib/api')
    vi.mocked(testTranslationModel).mockResolvedValue({
      ok: true,
      preserves_proper_nouns: true,
      glossary_json_valid: true,
      sec_per_segment: 2.1,
      sample_translation: 'Powiedz mi... po Spidera.',
      sample_glossary: ['Spider', 'Jake'],
      detail: 'all good',
    })
    render(
      <TestModelButton
        provider="ollama"
        url="http://ollama.local:11434"
        model="gemma3:27b"
        apiKey=""
        targetLanguage="pl"
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Test this model/i }))
    await vi.waitFor(() =>
      expect(vi.mocked(testTranslationModel)).toHaveBeenCalledWith({
        provider: 'ollama',
        url: 'http://ollama.local:11434',
        model: 'gemma3:27b',
        api_key: undefined,
        target_language: 'pl',
      }),
    )
  })

  it('renders the green "Looks good" verdict for a recommended-tier model', async () => {
    const { testTranslationModel } = await import('@/lib/api')
    vi.mocked(testTranslationModel).mockResolvedValue({
      ok: true,
      preserves_proper_nouns: true,
      glossary_json_valid: true,
      sec_per_segment: 2.1,
      sample_translation: 'Powiedz mi… po Spidera.',
      sample_glossary: ['Spider', 'Jake', 'Neytiri', 'Pandora'],
      detail: 'fine',
    })
    render(
      <TestModelButton provider="ollama" url="x" model="gemma3:27b" apiKey="" />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Test this model/i }))
    expect(await screen.findByText(/Looks good/i)).toBeInTheDocument()
    // The detail rows for each check are present + checkmarked.
    expect(screen.getByText(/Preserves proper nouns/i)).toBeInTheDocument()
    expect(screen.getByText(/Glossary returns valid JSON/i)).toBeInTheDocument()
    // Latency is humanised: "2.1s per cue".
    expect(screen.getByText(/2\.1s/)).toBeInTheDocument()
  })

  it('renders the yellow "Caveats" verdict when one check fails', async () => {
    // The classic aya pattern: translation preserves names but glossary
    // collapses to prose. ok=false, but neither catastrophic enough to
    // be red.
    const { testTranslationModel } = await import('@/lib/api')
    vi.mocked(testTranslationModel).mockResolvedValue({
      ok: false,
      preserves_proper_nouns: true,
      glossary_json_valid: false,
      sec_per_segment: 3.4,
      sample_translation: 'Powiedz mi… po Spidera.',
      sample_glossary: null,
      detail: 'partial',
    })
    render(
      <TestModelButton provider="ollama" url="x" model="aya-expanse:32b" apiKey="" />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Test this model/i }))
    expect(await screen.findByText(/Caveats/i)).toBeInTheDocument()
  })

  it('renders an inline error when the probe endpoint itself throws', async () => {
    const { testTranslationModel, ApiRequestError } = await import('@/lib/api')
    vi.mocked(testTranslationModel).mockRejectedValue(
      new ApiRequestError(500, 'INTERNAL_ERROR', 'Backend crashed'),
    )
    render(
      <TestModelButton provider="ollama" url="x" model="any" apiKey="" />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Test this model/i }))
    expect(await screen.findByText(/Backend crashed/)).toBeInTheDocument()
    expect(screen.getByText(/Probe failed to run/i)).toBeInTheDocument()
  })

  it('shows the loading state while the probe is in flight', async () => {
    // Mock a never-resolving promise so we can observe the running state.
    const { testTranslationModel } = await import('@/lib/api')
    let _resolve: (v: unknown) => void = () => {}
    vi.mocked(testTranslationModel).mockReturnValue(
      new Promise((resolve) => {
        _resolve = resolve as (v: unknown) => void
      }) as Promise<never>,
    )
    render(
      <TestModelButton provider="ollama" url="x" model="any" apiKey="" />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Test this model/i }))
    expect(await screen.findByText(/Running probes/i)).toBeInTheDocument()
    // Settle the promise so the test cleans up.
    _resolve({
      ok: true,
      preserves_proper_nouns: true,
      glossary_json_valid: true,
      sec_per_segment: 1,
      sample_translation: 'x',
      sample_glossary: [],
      detail: '',
    })
  })
})
