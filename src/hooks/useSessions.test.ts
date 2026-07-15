import { act, renderHook } from '@testing-library/react'
import { useSessions } from './useSessions'

describe('useSessions', () => {
  it('starts with the two design-baseline sessions', () => {
    const { result } = renderHook(() => useSessions())
    expect(result.current.sessions).toHaveLength(2)
    expect(result.current.activeId).toBe(result.current.sessions[0].id)
    expect(result.current.sessions[0].name).toBe('状态评估')
    expect(result.current.sessions[0].messageCount).toBe(1)
  })

  it('creates a new session and makes it active', () => {
    const { result } = renderHook(() => useSessions())
    act(() => result.current.createSession())
    expect(result.current.sessions).toHaveLength(3)
    expect(result.current.activeId).toBe(result.current.sessions[2].id)
    expect(result.current.sessions[2].messageCount).toBe(1)
  })

  it('updates the message count for only the targeted session', () => {
    const { result } = renderHook(() => useSessions())
    const [first, second] = result.current.sessions.map((session) => session.id)
    act(() => result.current.setMessageCount(first, 3))
    expect(result.current.sessions.find((session) => session.id === first)?.messageCount).toBe(3)
    expect(result.current.sessions.find((session) => session.id === second)?.messageCount).toBe(1)
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
    act(() => result.current.createSession()) // new session is now active
    const activeBefore = result.current.activeId
    act(() => result.current.deleteSession(first))
    expect(result.current.sessions).toHaveLength(2)
    expect(result.current.activeId).toBe(activeBefore)
  })

  it('deleting the active session falls back to the first remaining', () => {
    const { result } = renderHook(() => useSessions())
    const first = result.current.sessions[0].id
    const second = result.current.sessions[1].id
    act(() => result.current.selectSession(second))
    act(() => result.current.deleteSession(second))
    expect(result.current.activeId).toBe(first)
  })

  it('deleting the last session auto-creates a fresh one', () => {
    const { result } = renderHook(() => useSessions())
    const [first, second] = result.current.sessions.map((session) => session.id)
    act(() => result.current.deleteSession(second))
    act(() => result.current.deleteSession(first))
    expect(result.current.sessions).toHaveLength(1)
    expect(result.current.sessions[0].id).not.toBe(first)
    expect(result.current.activeId).toBe(result.current.sessions[0].id)
    expect(result.current.sessions[0].messageCount).toBe(1)
  })
})
