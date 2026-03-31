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
import { authAPI } from "@/lib/api"
import { toast } from "sonner"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

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

      const data = await authAPI.login({ email, password })

      if (data.access_token) {
        localStorage.setItem("auth_token", data.access_token)
      }
      if (data.refresh_token) {
        localStorage.setItem("refresh_token", data.refresh_token)
      }

      const authenticatedUser = {
        id: data.user_id,
        email: data.email,
        name: data.email.split("@")[0],
        role: "student" as const,
      }
      setUser(authenticatedUser)

      toast.success(data.message || "Login successful!")
      router.push("/dashboard")
    } catch (error: any) {
      toast.error(formatApiError(error, "Login failed"))
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
              <h1 className="text-2xl font-bold gradient-text">Welcome Back</h1>
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
