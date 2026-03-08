"use client"

import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { ArrowRight, Brain, Zap, Target, Users } from "lucide-react"
import Link from "next/link"
import { useAuthStore } from "@/lib/store"
import { useEffect, useState } from "react"

export default function Home() {
  const { user } = useAuthStore()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  if (!mounted) return null

  return (
    <>
      <Navbar />
      <main className="pt-20">
        {/* Hero Section */}
        <section className="min-h-screen flex items-center relative overflow-hidden hero-bg">
          {/* Background gradient effects */}
          <div className="absolute inset-0 -z-10 bg-black/60" />

          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 w-full">
            <div className="text-center space-y-8">
              <div className="space-y-4">
                <h1 className="text-5xl md:text-7xl font-bold gradient-text text-balance">
                  Learn Smart.
                  Assess Deep. 
                  Interview Ready.
                </h1>
                <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto text-balance">
                  Intelligent learning platform powered by AI. Personalized recommendations, adaptive quizzes, and
                  interview preparation all in one place.
                </p>
              </div>

              <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                {user ? (
                  <Link href="/dashboard">
                    <Button size="lg" className="bg-gradient-to-r from-primary to-accent hover:opacity-90 glow">
                      Go to Dashboard
                      <ArrowRight className="ml-2 w-4 h-4" />
                    </Button>
                  </Link>
                ) : (
                  <>
                    <Link href="/signup">
                      <Button size="lg" className="bg-gradient-to-r from-primary to-accent hover:opacity-90 glow">
                        Get Started
                        <ArrowRight className="ml-2 w-4 h-4" />
                      </Button>
                    </Link>
                    <Link href="/login">
                      <Button
                        size="lg"
                        variant="outline"
                        className="border-primary/50 text-foreground hover:bg-primary/10 bg-transparent"
                      >
                        Explore Demo
                      </Button>
                    </Link>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Features Section */}
        <section className="py-20 px-4 sm:px-6 lg:px-8">
          <div className="max-w-7xl mx-auto">
            <h2 className="text-3xl md:text-4xl font-bold text-center mb-12 gradient-text">Why Choose EduNerve?</h2>
            <div className="grid md:grid-cols-2 gap-8">
              {[
                {
                  icon: Brain,
                  title: "AI-Powered Learning",
                  description: "Personalized learning paths adapted to your pace and style",
                },
                {
                  icon: Target,
                  title: "Smart Assessments",
                  description: "Adaptive quizzes that evolve based on your performance",
                },
                {
                  icon: Zap,
                  title: "Interview Ready",
                  description: "Practice with AI interviewer and get real-time feedback",
                },
                {
                  icon: Users,
                  title: "Community Support",
                  description: "Learn with peers and get guidance from mentors",
                },
              ].map((feature, i) => (
                <div key={i} className="glass p-8 group hover:bg-white/15 transition-all">
                  <feature.icon className="w-8 h-8 text-accent mb-4" />
                  <h3 className="text-xl font-semibold mb-2">{feature.title}</h3>
                  <p className="text-muted-foreground">{feature.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>
    </>
  )
}
