import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import LanguageSelector from './LanguageSelector'

describe('LanguageSelector', () => {
  it('renders Auto-detect first when query is empty', () => {
    render(<LanguageSelector value="auto" onChange={() => {}} />)
    const list = screen.getByRole('list', { name: 'Language options' })
    const items = list.querySelectorAll('button')
    expect(items[0]).toHaveTextContent('Auto-detect')
  })

  it('shows the selected language as a pressed button', () => {
    render(<LanguageSelector value="fr" onChange={() => {}} />)
    const fr = screen.getByRole('button', { name: /Français/ })
    expect(fr).toHaveAttribute('aria-pressed', 'true')
  })

  it('calls onChange with the language code when an option is clicked', () => {
    const onChange = vi.fn()
    render(<LanguageSelector value="auto" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /Français/ }))
    expect(onChange).toHaveBeenCalledWith('fr')
  })

  it('filters the list by English name', () => {
    render(<LanguageSelector value="auto" onChange={() => {}} />)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'german' } })
    const list = screen.getByRole('list', { name: 'Language options' })
    expect(list).toHaveTextContent('Deutsch')
    expect(list).not.toHaveTextContent('Français')
  })

  it('hides Auto-detect from the option list when the query does not match it', () => {
    // Use a non-auto initial value so the label header doesn't show "Auto-detect".
    render(<LanguageSelector value="fr" onChange={() => {}} />)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'german' } })
    const list = screen.getByRole('list', { name: 'Language options' })
    expect(list).not.toHaveTextContent('Auto-detect')
  })

  it('shows a no-match message when nothing matches', () => {
    render(<LanguageSelector value="auto" onChange={() => {}} />)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'zzzzzz' } })
    expect(screen.getByText('No matching languages.')).toBeInTheDocument()
  })

  it('matches by native script', () => {
    render(<LanguageSelector value="auto" onChange={() => {}} />)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '日本語' } })
    expect(screen.getByText('日本語')).toBeInTheDocument()
  })

  it('omits Auto-detect entirely when excludeAuto=true', () => {
    // Auto-detect is meaningful only as a SOURCE-detection signal — used as
    // a translation target it produces nonsense prompts ("translate this to
    // auto"). Callers pass excludeAuto=true when the picker drives a
    // translation target (SubmitSheet/GenerationPanel with translate=ON).
    render(<LanguageSelector value="fr" onChange={() => {}} excludeAuto />)
    const list = screen.getByRole('list', { name: 'Language options' })
    expect(list).not.toHaveTextContent('Auto-detect')
  })

  it('keeps Auto-detect hidden even when query matches "auto"', () => {
    // Defence against a "search 'auto' to find it" bypass. Once excluded,
    // the option is gone regardless of the search term.
    render(<LanguageSelector value="fr" onChange={() => {}} excludeAuto />)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'auto' } })
    const list = screen.getByRole('list', { name: 'Language options' })
    expect(list).not.toHaveTextContent('Auto-detect')
  })
})
