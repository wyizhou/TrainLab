import { useReducer } from 'react'

export type Session = {
  id: string
  name: string
  messageCount: number
}

type State = {
  sessions: Session[]
  activeId: string
  // Monotonic counter kept in state (not a ref) so the reducer stays pure and
  // StrictMode's double-invoke can't drift the session numbering.
  counter: number
}

type Action =
  | { type: 'create' }
  | { type: 'select'; id: string }
  | { type: 'rename'; id: string; name: string }
  | { type: 'delete'; id: string }

function makeSession(n: number): Session {
  return { id: `s${n}`, name: `会话 ${n}`, messageCount: 0 }
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'create': {
      const n = state.counter + 1
      const session = makeSession(n)
      return { sessions: [...state.sessions, session], activeId: session.id, counter: n }
    }
    case 'select':
      return { ...state, activeId: action.id }
    case 'rename':
      return {
        ...state,
        sessions: state.sessions.map((session) =>
          session.id === action.id
            ? { ...session, name: action.name.trim() || session.name }
            : session,
        ),
      }
    case 'delete': {
      const remaining = state.sessions.filter((session) => session.id !== action.id)
      // Deleting the last session auto-creates a fresh one (never empty).
      if (remaining.length === 0) {
        const n = state.counter + 1
        const session = makeSession(n)
        return { sessions: [session], activeId: session.id, counter: n }
      }
      // Deleting the active session falls back to the first remaining one.
      const activeId = state.activeId === action.id ? remaining[0].id : state.activeId
      return { ...state, sessions: remaining, activeId }
    }
    default:
      return state
  }
}

function init(): State {
  const session = makeSession(1)
  return { sessions: [session], activeId: session.id, counter: 1 }
}

export function useSessions() {
  const [state, dispatch] = useReducer(reducer, undefined, init)
  return {
    sessions: state.sessions,
    activeId: state.activeId,
    createSession: () => dispatch({ type: 'create' }),
    selectSession: (id: string) => dispatch({ type: 'select', id }),
    renameSession: (id: string, name: string) => dispatch({ type: 'rename', id, name }),
    deleteSession: (id: string) => dispatch({ type: 'delete', id }),
  }
}
