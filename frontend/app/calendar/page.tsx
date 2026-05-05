"use client"

import { Navbar } from "@/components/navbar"
import { CalendarTask } from "@/components/calendar-task"

export default function CalendarTaskPage() {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(124,58,237,0.12),_transparent_55%),radial-gradient(circle_at_20%_40%,_rgba(16,185,129,0.1),_transparent_50%),radial-gradient(circle_at_80%_30%,_rgba(14,165,233,0.1),_transparent_45%)]">
      <Navbar />
      <main className="container mx-auto px-4 py-10">
        <div className="mb-8 rounded-3xl border border-border/60 bg-background/60 p-6 shadow-lg shadow-black/5 backdrop-blur">
          <h1 className="text-3xl font-semibold tracking-tight">Calendar Task Tracker</h1>
          <p className="text-sm text-muted-foreground mt-2">
            Plan your interview prep tasks, track readiness, and gather feedback on the day of each task
          </p>
        </div>
        
        <CalendarTask />
      </main>
    </div>
  )
}
