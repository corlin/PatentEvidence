import React, { createContext, useContext, useEffect, useState } from 'react'

interface RouterContextValue {
  pathname: string
  search: string
  params: Record<string, string>
  navigate: (to: string) => void
}

const RouterContext = createContext<RouterContextValue | undefined>(undefined)

export function matchPath(
  pattern: string,
  pathname: string
): { matched: boolean; params: Record<string, string> } {
  const patternSegments = pattern.split('/').filter(Boolean)
  const pathSegments = pathname.split('/').filter(Boolean)

  if (patternSegments.length !== pathSegments.length) {
    return { matched: false, params: {} }
  }

  const params: Record<string, string> = {}
  for (let i = 0; i < patternSegments.length; i++) {
    const patternSeg = patternSegments[i]
    const pathSeg = pathSegments[i]

    if (patternSeg.startsWith(':')) {
      const paramName = patternSeg.slice(1)
      params[paramName] = decodeURIComponent(pathSeg)
    } else if (patternSeg !== pathSeg) {
      return { matched: false, params: {} }
    }
  }

  return { matched: true, params }
}

export const Router: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentPath, setCurrentPath] = useState(window.location.pathname)
  const [currentSearch, setCurrentSearch] = useState(window.location.search)

  useEffect(() => {
    const handlePopState = () => {
      setCurrentPath(window.location.pathname)
      setCurrentSearch(window.location.search)
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const navigate = (to: string) => {
    if (to === currentPath + currentSearch) return
    window.history.pushState({}, '', to)
    const url = new URL(to, window.location.origin)
    setCurrentPath(url.pathname)
    setCurrentSearch(url.search)
  }

  return (
    <RouterContext.Provider
      value={{
        pathname: currentPath,
        search: currentSearch,
        params: {},
        navigate,
      }}
    >
      {children}
    </RouterContext.Provider>
  )
}

export function useRouter(): RouterContextValue {
  const context = useContext(RouterContext)
  if (!context) {
    throw new Error('useRouter must be used within a Router')
  }
  return context
}

export function useNavigate() {
  const { navigate } = useRouter()
  return navigate
}

export const Link: React.FC<
  React.AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }
> = ({ to, onClick, children, ...rest }) => {
  const navigate = useNavigate()

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (onClick) onClick(e)
    if (!e.defaultPrevented && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) {
      e.preventDefault()
      navigate(to)
    }
  }

  return (
    <a href={to} onClick={handleClick} {...rest}>
      {children}
    </a>
  )
}
