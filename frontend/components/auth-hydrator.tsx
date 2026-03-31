"use client"

import { useEffect } from "react"
import { useAuthStore } from "@/lib/store"

export function AuthHydrator() {
  const hydrateFromStorage = useAuthStore((state) => state.hydrateFromStorage)
  const hasHydrated = useAuthStore((state) => state.hasHydrated)

  useEffect(() => {
    if (!hasHydrated) {
      hydrateFromStorage()
    }
  }, [hasHydrated, hydrateFromStorage])

  return null
}
