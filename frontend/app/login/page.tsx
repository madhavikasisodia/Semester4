"use client"

import type React from "react"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { useAuthStore } from "@/lib/store"
import { formatApiError } from "@/lib/utils"
import { toast } from "sonner"
import Link from "next/link"
import { ArrowLeft, Brain } from "lucide-react"

export default function LoginPage() {
  const router = useRouter()
  const { setUser } = useAuthStore()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      if (!email || password.length < 6) {
        toast.error("Please enter valid email and password (min 6 characters)")
        setLoading(false)
        return
      }

      // Call real backend login endpoint
      const response = await fetch('http://localhost:8000/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      })

      const data = await response.json()

      if (response.ok) {
        // Save real JWT token
        localStorage.setItem("auth_token", data.access_token)
        
        // Set user in store
        const mockUser = {
          id: Math.random().toString(36).substr(2, 9),
          email,
          name: email.split("@")[0],
          role: "student" as const,
        }
        setUser(mockUser)
        
        toast.success("Login successful!")
        router.push("/dashboard")
      } else {
        // Handle specific error messages from backend
        const apiMessage = formatApiError(
          data?.detail ?? data?.message ?? data,
          "Login failed",
        )
        toast.error(apiMessage)
      }
    } catch (error: any) {
      toast.error(error.message || "Login failed. Please check your connection.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Navbar />
      <main className="min-h-screen pt-20 flex items-center justify-center px-4">
        <div className="absolute inset-0 -z-10">
          <div className="absolute top-20 left-10 w-72 h-72 bg-primary/20 rounded-full blur-3xl opacity-30 animate-pulse" />
          <div className="absolute bottom-20 right-10 w-72 h-72 bg-accent/20 rounded-full blur-3xl opacity-30 animate-pulse" />
        </div>

        <Card className="glass w-full max-w-md p-8">
          <div className="space-y-6">
            <Link
              href="/"
              className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Back</span>
            </Link>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-lg bg-gradient-to-br from-primary to-accent glow">
                  <Brain className="w-5 h-5 text-foreground" />
                </div>
                <h1 className="text-2xl font-bold gradient-text">Welcome Back</h1>
              </div>
              <p className="text-sm text-muted-foreground">Sign in to your account to continue</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="text-sm font-medium">Email</label>
                <Input
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="mt-2 bg-white/5 border-white/20"
                  required
                />
              </div>

              <div>
                <label className="text-sm font-medium">Password</label>
                <Input
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="mt-2 bg-white/5 border-white/20"
                  required
                />
              </div>

              <Button
                type="submit"
                disabled={loading}
                className="w-full bg-gradient-to-r from-primary to-accent hover:opacity-90 glow"
              >
                {loading ? "Signing in..." : "Sign In"}
              </Button>
            </form>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-white/10" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-background px-2 text-muted-foreground">Don't have an account?</span>
              </div>
            </div>

            <Link href="/signup">
              <Button
                variant="outline"
                className="w-full border-primary/50 text-foreground hover:bg-primary/10 bg-transparent"
              >
                Create Account
              </Button>
            </Link>
          </div>
        </Card>
      </main>
    </>
  )
}
