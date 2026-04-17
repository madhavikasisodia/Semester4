import { create } from "zustand"

interface User {
  id: string
  email: string
  name: string
  role: "student" | "admin"
  jobPreference?: string
}

interface AuthStore {
  user: User | null
  isLoading: boolean
  hasHydrated: boolean
  setUser: (user: User | null) => void
  setLoading: (loading: boolean) => void
  logout: () => void
  hydrateFromStorage: () => void
}

const USER_STORAGE_KEY = "edunerve_user"

const getStoredUser = (): User | null => {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(USER_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch (error) {
    console.warn("Failed to parse stored user", error)
    return null
  }
}

const persistUser = (user: User | null) => {
  if (typeof window === "undefined") return
  if (!user) {
    window.localStorage.removeItem(USER_STORAGE_KEY)
    return
  }
  window.localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user))
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  isLoading: false,
  hasHydrated: false,
  setUser: (user) => {
    persistUser(user)
    set({ user, hasHydrated: true })
  },
  setLoading: (isLoading) => set({ isLoading }),
  logout: () => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem("auth_token")
      window.localStorage.removeItem("token")
      window.localStorage.removeItem("access_token")
      window.localStorage.removeItem("refresh_token")
    }
    persistUser(null)
    set({ user: null, hasHydrated: true })
  },
  hydrateFromStorage: () => {
    if (typeof window === "undefined") return
    set({ user: getStoredUser(), hasHydrated: true })
  },
}))
