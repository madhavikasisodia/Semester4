"use client"

import type React from "react"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { useAuthStore } from "@/lib/store"
import { formatApiError } from "@/lib/utils"
import { authAPI } from "@/lib/api"
import { toast } from "sonner"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

const JOB_OPTIONS = [
  { value: "software-developer", label: "Software Developer" },
  { value: "data-scientist", label: "Data Scientist" },
  { value: "web-developer", label: "Web Developer" },
  { value: "cybersecurity-analyst", label: "Cybersecurity Analyst" },
  { value: "database-administrator", label: "Database Administrator" },
  { value: "network-administrator", label: "Network Administrator" },
  { value: "it-consultant", label: "IT Consultant" },
  { value: "game-developer", label: "Game Developer" },
  { value: "ai-ml-engineer", label: "AI/ML Engineer" },
]

export default function SignupPage() {
  const router = useRouter()
  const { setUser } = useAuthStore()
  const [formData, setFormData] = useState({
    email: "",
    password: "",
    name: "",
    confirmPassword: "",
    jobPreference: "",
  })
  const [loading, setLoading] = useState(false)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({ ...prev, [name]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (formData.password !== formData.confirmPassword) {
      toast.error("Passwords do not match")
      return
    }

    if (formData.password.length < 6) {
      toast.error("Password must be at least 6 characters")
      return
    }

    if (!formData.jobPreference) {
      toast.error("Select your job preference")
      return
    }

    setLoading(true)

    try {
      const payload = {
        email: formData.email,
        password: formData.password,
        metadata: {
          username: formData.email.split("@")[0],
          full_name: formData.name,
          job_preference: formData.jobPreference,
        },
      }

      const data = await authAPI.signup(payload)

      if (data.access_token) {
        localStorage.setItem("auth_token", data.access_token)
        localStorage.setItem("token", data.access_token)
        localStorage.setItem("access_token", data.access_token)
      }
      if (data.refresh_token) {
        localStorage.setItem("refresh_token", data.refresh_token)
      }

      const newUser = {
        id: data.user_id,
        email: data.email,
        name: formData.name || data.email.split("@")[0],
        role: "student" as const,
        jobPreference: formData.jobPreference,
      }
      setUser(newUser)

      const successMessage = data.access_token
        ? "Account created successfully!"
        : "Account created. Please confirm your email to continue."
      toast.success(successMessage)

      router.push(data.access_token ? "/dashboard" : "/login")
    } catch (error: any) {
      toast.error(formatApiError(error, "Signup failed"))
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
              <h1 className="text-2xl font-bold gradient-text">Join EduNerve</h1>
              <p className="text-sm text-muted-foreground">Start your learning journey today</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="text-sm font-medium">Full Name</label>
                <Input
                  type="text"
                  name="name"
                  value={formData.name}
                  onChange={handleChange}
                  className="mt-2 bg-white/5 border-white/20"
                  required
                />
              </div>

              <div>
                <label className="text-sm font-medium">Email</label>
                <Input
                  type="email"
                  name="email"
                  value={formData.email}
                  onChange={handleChange}
                  className="mt-2 bg-white/5 border-white/20"
                  required
                />
              </div>

              <div>
                <label className="text-sm font-medium">Job Preference</label>
                <Select
                  value={formData.jobPreference}
                  onValueChange={(value) =>
                    setFormData((prev) => ({
                      ...prev,
                      jobPreference: value,
                    }))
                  }
                >
                  <SelectTrigger className="mt-2 bg-white/5 border-white/20">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {JOB_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className="text-sm font-medium">Password</label>
                <Input
                  type="password"
                  name="password"
                  value={formData.password}
                  onChange={handleChange}
                  className="mt-2 bg-white/5 border-white/20"
                  required
                />
              </div>

              <div>
                <label className="text-sm font-medium">Confirm Password</label>
                <Input
                  type="password"
                  name="confirmPassword"
                  value={formData.confirmPassword}
                  onChange={handleChange}
                  className="mt-2 bg-white/5 border-white/20"
                  required
                />
              </div>

              <Button
                type="submit"
                disabled={loading}
                className="w-full bg-gradient-to-r from-primary to-accent hover:opacity-90 glow"
              >
                {loading ? "Creating account..." : "Create Account"}
              </Button>
            </form>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-white/10" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-background px-2 text-muted-foreground">Already have an account?</span>
              </div>
            </div>

            <Link href="/login">
              <Button
                variant="outline"
                className="w-full border-primary/50 text-foreground hover:bg-primary/10 bg-transparent"
              >
                Sign In
              </Button>
            </Link>
          </div>
        </Card>
      </main>
    </>
  )
}
