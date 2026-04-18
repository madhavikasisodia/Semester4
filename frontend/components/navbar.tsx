"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { useAuthStore } from "@/lib/store"
import {
  BookOpen,
  BrainCircuit,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  Sparkles,
  Target,
  Trophy,
  X,
} from "lucide-react"
import { useState, useEffect } from "react"
import { ThemeToggle } from "@/components/theme-toggle"

export function Navbar() {
  const pathname = usePathname()
  const { user, logout } = useAuthStore()
  const [menuOpen, setMenuOpen] = useState(false)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    document.body.style.overflow = menuOpen ? "hidden" : ""
    return () => {
      document.body.style.overflow = ""
    }
  }, [menuOpen])

  const navLinks = [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/learning", label: "Learning", icon: BookOpen },
    { href: "/recommendations", label: "Recommendations", icon: Sparkles },
    { href: "/progress", label: "Progress", icon: Target },
    { href: "/resume", label: "Resume", icon: FileText },
    { href: "/interview", label: "Interview", icon: BrainCircuit },
    { href: "/tests", label: "Tests", icon: Trophy },
  ]

  const sidebarContent = (
    <>
      <div className="border-b border-border px-5 py-5">
        <Link href="/" className="flex items-center gap-2 group">
          <span className="font-bold text-lg gradient-text tracking-wide">EduNerve</span>
        </Link>
      </div>

      {mounted && user ? (
        <>
          <div className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
            {navLinks.map((link) => {
              const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`)
              const Icon = link.icon

              return (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setMenuOpen(false)}
                  className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-primary/15 text-foreground border border-primary/30"
                      : "text-muted-foreground hover:text-foreground hover:bg-foreground/5"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{link.label}</span>
                </Link>
              )
            })}
          </div>

          <div className="border-t border-border p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground truncate">{user.name}</p>
              <ThemeToggle />
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                logout()
                window.location.href = "/"
              }}
              className="w-full flex items-center gap-2 justify-center"
            >
              <LogOut className="w-4 h-4" />
              <span>Logout</span>
            </Button>
          </div>
        </>
      ) : mounted ? (
        <div className="flex-1 p-4 flex flex-col gap-3 justify-end">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Theme</span>
            <ThemeToggle />
          </div>
          <Link href="/login" onClick={() => setMenuOpen(false)}>
            <Button variant="ghost" size="sm" className="w-full">
              Login
            </Button>
          </Link>
          <Link href="/signup" onClick={() => setMenuOpen(false)}>
            <Button size="sm" className="w-full bg-linear-to-r from-primary to-accent hover:opacity-90">
              Sign Up
            </Button>
          </Link>
        </div>
      ) : (
        <div className="flex-1 p-4">
          <ThemeToggle />
        </div>
      )}
    </>
  )

  return (
    <>
      <header className="fixed top-0 inset-x-0 z-50 h-16 glass-dark border-b border-border">
        <div className="h-full px-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
          <button
            aria-label={menuOpen ? "Close navigation" : "Open navigation"}
            className="p-2 rounded-lg border border-border/60 bg-background/60"
            onClick={() => setMenuOpen((prev) => !prev)}
          >
            {menuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
          <Link href="/" className="font-bold text-base gradient-text tracking-wide">
            EduNerve
          </Link>
          </div>

          {mounted && (
            <div className="hidden md:flex items-center gap-2">
              <ThemeToggle />
              {user ? (
                <>
                  <Link href="/dashboard">
                    <Button variant="ghost" size="sm">
                      Dashboard
                    </Button>
                  </Link>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      logout()
                      window.location.href = "/"
                    }}
                  >
                    Logout
                  </Button>
                </>
              ) : (
                <>
                  <Link href="/login">
                    <Button variant="ghost" size="sm">
                      Sign In
                    </Button>
                  </Link>
                  <Link href="/signup">
                    <Button size="sm" className="bg-linear-to-r from-primary to-accent hover:opacity-90">
                      Sign Up
                    </Button>
                  </Link>
                </>
              )}
            </div>
          )}
        </div>
      </header>

      {menuOpen && (
        <div className="fixed inset-0 z-40">
          <button
            aria-label="Close navigation overlay"
            className="absolute inset-0 bg-black/50"
            onClick={() => setMenuOpen(false)}
          />
          <aside className="absolute left-0 top-0 h-full w-72 max-w-[85vw] glass-dark border-r border-border flex flex-col">
            {sidebarContent}
          </aside>
        </div>
      )}

      <div className="h-16" aria-hidden="true" />
    </>
  )
}
