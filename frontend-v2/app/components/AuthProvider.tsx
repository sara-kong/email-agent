'use client'

import { createContext, useContext, useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { apiFetch } from '@/lib/api'

type User = { user_id: string; email: string }

type AuthContextValue = {
  user: User | null
  loading: boolean
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  logout: async () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}

const PUBLIC_PATHS = ['/login']

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // Check the session once on mount.
  useEffect(() => {
    apiFetch('/api/auth/me')
      .then(res => res.ok ? res.json() : null)
      .then(data => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  // Redirect based on auth state whenever the route changes.
  useEffect(() => {
    if (loading) return
    if (!user && !PUBLIC_PATHS.includes(pathname)) {
      router.replace('/login')
    } else if (user && PUBLIC_PATHS.includes(pathname)) {
      router.replace('/')
    }
  }, [user, loading, pathname, router])

  async function logout() {
    await apiFetch('/api/auth/logout', { method: 'POST' })
    setUser(null)
    router.replace('/login')
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-stone-50">
        <p className="text-stone-400 text-sm">Loading...</p>
      </div>
    )
  }

  if (!user && !PUBLIC_PATHS.includes(pathname)) {
    return null
  }

  return (
    <AuthContext.Provider value={{ user, loading, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
