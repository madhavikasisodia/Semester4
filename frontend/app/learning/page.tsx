"use client"

import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { CheckCircle2, Clock3, RefreshCw, Sparkles, Target } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import {
  learningAPI,
  type LearningRoadmap,
  type ReadinessAnalytics,
  type ReminderItem,
} from "@/lib/api"

const formatError = (err: any): string => {
  if (typeof err === "string") return err
  if (typeof err?.response?.data?.detail === "string") return err.response.data.detail
  return err?.message || "Something went wrong"
}

export default function LearningPage() {
  const [roadmap, setRoadmap] = useState<LearningRoadmap | null>(null)
  const [reminders, setReminders] = useState<ReminderItem[]>([])
  const [readiness, setReadiness] = useState<ReadinessAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshingRoadmap, setRefreshingRoadmap] = useState(false)

  const pendingReminders = useMemo(
    () => reminders.filter((item) => item.status === "pending"),
    [reminders]
  )

  const fetchLearningData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [roadmapData, remindersData, readinessData] = await Promise.all([
        learningAPI.getLearningRoadmap(),
        learningAPI.getReminders(),
        learningAPI.getReadinessAnalytics(),
      ])
      setRoadmap(roadmapData)
      setReminders(remindersData)
      setReadiness(readinessData)
    } catch (err: any) {
      setError(formatError(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLearningData()
  }, [])

  const refreshRoadmap = async () => {
    setRefreshingRoadmap(true)
    setError(null)
    try {
      const updated = await learningAPI.regenerateLearningRoadmap()
      setRoadmap(updated)
    } catch (err: any) {
      setError(formatError(err))
    } finally {
      setRefreshingRoadmap(false)
    }
  }

  const markReminderDone = async (reminderId: number) => {
    try {
      await learningAPI.updateReminderStatus(reminderId, "done")
      setReminders((prev) => prev.map((item) => (item.id === reminderId ? { ...item, status: "done" } : item)))
    } catch (err: any) {
      setError(formatError(err))
    }
  }

  return (
    <>
      <Navbar />
      <main className="pt-20 pb-12">
        <div className="min-h-screen relative">
          <div className="absolute inset-0 -z-10">
            <div className="absolute top-20 left-10 w-72 h-72 bg-primary/10 rounded-full blur-3xl opacity-20" />
            <div className="absolute bottom-20 right-10 w-72 h-72 bg-accent/10 rounded-full blur-3xl opacity-20" />
          </div>

          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-8">
            <div className="space-y-4">
              <h1 className="text-4xl font-bold gradient-text">Personalized Learning</h1>
              <p className="text-muted-foreground max-w-2xl">
                Adaptive roadmap and reminders generated from your interview and mock-test performance
              </p>
            </div>

            {error && (
              <Card className="p-4 border-destructive/50 bg-destructive/10 text-destructive">{error}</Card>
            )}

            <div className="grid md:grid-cols-3 gap-4">
              <Card className="p-5 space-y-2">
                <div className="flex items-center gap-2 text-muted-foreground text-sm">
                  <Target className="w-4 h-4" />
                  Readiness Score
                </div>
                <div className="text-3xl font-bold">{readiness?.readiness_score ?? 0}</div>
              </Card>
              <Card className="p-5 space-y-2">
                <div className="flex items-center gap-2 text-muted-foreground text-sm">
                  <Sparkles className="w-4 h-4" />
                  Avg Mock-Test Score
                </div>
                <div className="text-3xl font-bold">{readiness?.avg_test_score ?? 0}%</div>
              </Card>
              <Card className="p-5 space-y-2">
                <div className="flex items-center gap-2 text-muted-foreground text-sm">
                  <Clock3 className="w-4 h-4" />
                  Pending Reminders
                </div>
                <div className="text-3xl font-bold">{pendingReminders.length}</div>
              </Card>
            </div>

            <Card className="p-6 space-y-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-2xl font-semibold">{roadmap?.title || "Learning Roadmap"}</h2>
                  <p className="text-sm text-muted-foreground">Weekly plan generated from your weak topics</p>
                </div>
                <Button onClick={refreshRoadmap} disabled={refreshingRoadmap || loading}>
                  <RefreshCw className={`w-4 h-4 mr-2 ${refreshingRoadmap ? "animate-spin" : ""}`} />
                  Regenerate
                </Button>
              </div>

              {loading && <p className="text-sm text-muted-foreground">Generating your roadmap...</p>}

              <div className="grid lg:grid-cols-2 gap-4">
                {(roadmap?.weeks || []).map((week) => (
                  <Card key={week.week} className="p-4 bg-muted/30 border-border/60">
                    <div className="text-sm text-muted-foreground">Week {week.week}</div>
                    <h3 className="font-semibold mt-1">{week.goal}</h3>
                    <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
                      {week.tasks.map((task, idx) => (
                        <li key={`${week.week}-${idx}`} className="flex items-start gap-2">
                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-primary" />
                          <span>{task}</span>
                        </li>
                      ))}
                    </ul>
                  </Card>
                ))}
              </div>
            </Card>

            <Card className="p-6 space-y-4">
              <h2 className="text-xl font-semibold">Action Reminders</h2>
              <div className="space-y-3">
                {pendingReminders.map((reminder) => (
                  <div key={reminder.id} className="flex items-center justify-between gap-4 border border-border/50 rounded-lg p-4">
                    <div>
                      <h3 className="font-medium">{reminder.title}</h3>
                      <p className="text-sm text-muted-foreground">{reminder.message}</p>
                      {reminder.due_at && (
                        <p className="text-xs text-muted-foreground mt-1">Due: {new Date(reminder.due_at).toLocaleString()}</p>
                      )}
                    </div>
                    <Button variant="outline" onClick={() => markReminderDone(reminder.id)}>
                      <CheckCircle2 className="w-4 h-4 mr-2" />
                      Mark Done
                    </Button>
                  </div>
                ))}
                {!loading && pendingReminders.length === 0 && (
                  <p className="text-sm text-muted-foreground">No pending reminders. Great consistency.</p>
                )}
              </div>
            </Card>

            <Card className="p-6 space-y-3">
              <h2 className="text-xl font-semibold">Top Weak Topics</h2>
              <div className="flex flex-wrap gap-2">
                {(readiness?.weak_topics || []).map((topic) => (
                  <span key={topic} className="text-xs px-3 py-1 rounded-full bg-primary/15 text-primary">
                    {topic}
                  </span>
                ))}
                {!loading && !(readiness?.weak_topics || []).length && (
                  <span className="text-sm text-muted-foreground">No weak-topic trend yet. Take more mock tests.</span>
                )}
              </div>
            </Card>
          </div>
        </div>
      </main>
    </>
  )
}
