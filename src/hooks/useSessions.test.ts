import { act, renderHook } from '@testing-library/react'
import { useSessions } from './useSessions'

describe('useSessions', () => {
  it('starts with a single active session', () => {
    const { result } = renderHook(() => useSessions())
    expect(result.current.sessions).toHaveLength(1)
    expect(result.current.activeId).toBe(result.current.sessions[0].id)
    expect(result.current.sessions[0].messageCount).toBe(0)
  })

  it('creates a new session and makes it active', () => {
    const { result } = renderHook(() => useSessions())
    act(() => result.current.createSession())
    expect(result.current.sessions).toHaveLength(2)
    expect(result.current.activeId).toBe(result.current.sessions[1].id)
  })

  it('renames a session; an empty name keeps the previous one', () => {
    const { result } = renderHook(() => useSessions())
    const id = result.current.sessions[0].id
    act(() => result.current.renameSession(id, '训练分析'))
    expect(result.current.sessions[0].name).toBe('训练分析')
    act(() => result.current.renameSession(id, '   '))
    expect(result.current.sessions[0].name).toBe('训练分析')
  })

  it('deleting a non-active session leaves the active selection untouched', () => {
    const { result } = renderHook(() => useSessions())
    const first = result.current.sessions[0].id
    act(() => result.current.createSession()) // second is now active
    const activeBefore = result.current.activeId
    act(() => result.current.deleteSession(first))
    expect(result.current.sessions).toHaveLength(1)
    expect(result.current.activeId).toBe(activeBefore)
  })

  it('deleting the active session falls back to the first remaining', () => {
    const { result } = renderHook(() => useSessions())
    const first = result.current.sessions[0].id
    act(() => result.current.createSession())
    const second = result.current.activeId
    expect(second).not.toBe(first)
    act(() => result.current.deleteSession(second))
    expect(result.current.activeId).toBe(first)
  })

  it('deleting the last session auto-creates a fresh one', () => {
    const { result } = renderHook(() => useSessions())
    const only = result.current.sessions[0].id
    act(() => result.current.deleteSession(only))
    expect(result.current.sessions).toHaveLength(1)
    expect(result.current.sessions[0].id).not.toBe(only)
    expect(result.current.activeId).toBe(result.current.sessions[0].id)
  })
})
