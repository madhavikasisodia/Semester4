"use client"

import Link from "next/link"
import { Button } from "@/components/ui/button"
import { useAuthStore } from "@/lib/store"
import { LogOut, Menu, X } from "lucide-react"
import { useState, useEffect } from "react"
import { ThemeToggle } from "@/components/theme-toggle"

export function Navbar() {
  const { user, logout } = useAuthStore()
  const [menuOpen, setMenuOpen] = useState(false)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const navLinks = [
    { href: "/dashboard", label: "Dashboard" },
    { href: "/recommendations", label: "Recommendations" },
    { href: "/progress", label: "Progress" },
    { href: "/interview", label: "Interview" },
  ]

  return (
    <nav className="fixed top-0 w-full z-50 glass-dark border-b">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 group">
          <span className="font-bold text-lg gradient-text">EduNerve</span>
        </Link>

        {mounted && user ? (
          <>
            {/* Desktop Navigation */}
            <div className="hidden md:flex items-center gap-6">
              {navLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  {link.label}
                </Link>
              ))}
            </div>

            <div className="flex items-center gap-4">
              <div className="hidden sm:flex items-center gap-2 text-sm text-muted-foreground">
                <span>Welcome, {user.name}</span>
              </div>
              
              {/* Theme Toggle */}
              <ThemeToggle />
              
              {/* Mobile Menu Button */}
              <button
                className="md:hidden p-2"
                onClick={() => setMenuOpen(!menuOpen)}
              >
                {menuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
              </button>

              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  logout()
                  window.location.href = "/"
                }}
                className="hidden md:flex items-center gap-2"
              >
                <LogOut className="w-4 h-4" />
                <span>Logout</span>
              </Button>
            </div>
          </>
        ) : mounted ? (
          <div className="flex items-center gap-3">
            {/* Theme Toggle */}
            <ThemeToggle />
            
            <Link href="/login">
              <Button variant="ghost" size="sm">
                Login
              </Button>
            </Link>
            <Link href="/signup">
              <Button size="sm" className="bg-gradient-to-r from-primary to-accent hover:opacity-90">
                Sign Up
              </Button>
            </Link>
          </div>
        ) : (
          // Fallback for when not mounted yet - prevents hydration mismatch
          <div className="flex items-center gap-3">
            <ThemeToggle />
          </div>
        )}
      </div>

      {/* Mobile Menu */}
      {mounted && user && menuOpen && (
        <div className="md:hidden border-t bg-background">
          <div className="px-4 py-4 space-y-3">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="block py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </Link>
            ))}
            <div className="flex items-center gap-2 py-2">
              <span className="text-sm text-muted-foreground">Theme:</span>
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
        </div>
      )}
    </nav>
  )
}
