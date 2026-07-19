import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import {
  GenerationControls,
  controlsBlockedReason,
  buildJobPayload,
  type GenerationControlsValues,
} from './GenerationControls'

// <Link> in GenerationControls requires a router context; wrap renders in MemoryRouter.
const renderInRouter = (ui: React.ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>)

const base: GenerationControlsValues = {
  sourceLanguage: 'auto', translate: false, targetLanguage: '', profileName: '',
  useExistingSubs: null,
}

describe('controlsBlockedReason', () => {
  it('blocks when no profiles exist', () => {
    expect(controlsBlockedReason(base, 0)).toMatch(/profile/i)
  })
  it('blocks when no profile selected', () => {
    expect(controlsBlockedReason(base, 2)).toMatch(/profile/i)
  })
  it('blocks translate without a concrete target', () => {
    expect(controlsBlockedReason({ ...base, profileName: 'p', translate: true, targetLanguage: '' }, 2)).toMatch(/target/i)
    expect(controlsBlockedReason({ ...base, profileName: 'p', translate: true, targetLanguage: 'auto' }, 2)).toMatch(/target/i)
  })
  it('passes with profile + translate off', () => {
    expect(controlsBlockedReason({ ...base, profileName: 'p' }, 2)).toBeNull()
  })
  it('passes with profile + concrete target', () => {
    expect(controlsBlockedReason({ ...base, profileName: 'p', translate: true, targetLanguage: 'pl' }, 2)).toBeNull()
  })
})

describe('buildJobPayload', () => {
  it('omits target_language when translate is off', () => {
    expect(buildJobPayload('/x.mkv', { ...base, profileName: 'p', translate: false, targetLanguage: 'pl' }))
      .toEqual({ file_path: '/x.mkv', profile_name: 'p', source_language: 'auto', translate: false })
  })
  it('includes target_language only when translate + concrete target', () => {
    expect(buildJobPayload('/x.mkv', { ...base, sourceLanguage: 'en', translate: true, targetLanguage: 'pl', profileName: 'p' }))
      .toEqual({ file_path: '/x.mkv', profile_name: 'p', source_language: 'en', translate: true, target_language: 'pl' })
  })
  it('omits use_existing_subs when untouched, includes explicit override', () => {
    expect(buildJobPayload('/x.mkv', { ...base, profileName: 'p' }).use_existing_subs).toBeUndefined()
    expect(buildJobPayload('/x.mkv', { ...base, profileName: 'p', useExistingSubs: false }).use_existing_subs).toBe(false)
    expect(buildJobPayload('/x.mkv', { ...base, profileName: 'p', useExistingSubs: true }).use_existing_subs).toBe(true)
  })
  it('omits target_language when translate + auto target', () => {
    const p = buildJobPayload('/x.mkv', { ...base, sourceLanguage: 'en', translate: true, targetLanguage: 'auto', profileName: 'p' })
    expect(p.target_language).toBeUndefined()
  })
})

describe('<GenerationControls>', () => {
  const profiles = [{ name: 'gemma' }, { name: 'groq' }] as never
  const noop = () => {}
  function setup(values = base) {
    const onChange = vi.fn()
    renderInRouter(
      <GenerationControls
        idPrefix="t" values={values} profiles={profiles}
        onChange={onChange} onProfileLinkClick={noop}
      />,
    )
    return { onChange }
  }
  it('shows the target selector only when translate is on', () => {
    setup({ ...base, translate: false })
    expect(screen.queryByText(/translate to/i)).not.toBeInTheDocument()
    setup({ ...base, translate: true })
    expect(screen.getByText(/translate to/i)).toBeInTheDocument()
  })
  it('renders the amber hint when translate + no concrete target', () => {
    setup({ ...base, profileName: 'gemma', translate: true, targetLanguage: '' })
    expect(screen.getByText(/Auto-detect is for source/i)).toBeInTheDocument()
  })
  it('toggling translate off clears target via onChange', async () => {
    const { onChange } = setup({ ...base, translate: true, targetLanguage: 'pl' })
    await userEvent.click(screen.getByRole('switch', { name: /translate subtitles/i }))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ translate: false, targetLanguage: '' }))
  })
  it('shows the empty-state link when no profiles', () => {
    renderInRouter(<GenerationControls idPrefix="t" values={{ ...base }} profiles={[] as never} onChange={vi.fn()} onProfileLinkClick={noop} />)
    expect(screen.getByText(/create one in settings/i)).toBeInTheDocument()
  })
})

describe('existing-subtitles switch', () => {
  const profiles = [{ name: 'gemma' }] as never
  it('shows the global default until touched, then reports an explicit override', async () => {
    const onChange = vi.fn()
    renderInRouter(
      <GenerationControls idPrefix="t" values={{ ...base }} profiles={profiles}
        onChange={onChange} existingSubsDefault={false} />,
    )
    const toggle = screen.getByRole('switch', { name: /use existing subtitles/i })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(toggle)
    expect(onChange).toHaveBeenCalledWith({ useExistingSubs: true })
  })
})
