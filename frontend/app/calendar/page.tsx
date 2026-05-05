"use client"

import { Navbar } from "@/components/navbar"
import { CalendarTask } from "@/components/calendar-task"

export default function CalendarTaskPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">📅 Calendar Task Tracker</h1>
          <p className="text-gray-600 mt-2">
            Plan your interview prep tasks, track readiness, and gather feedback on the day of each task
          </p>
        </div>
        
        <CalendarTask />
      </main>
    </div>
  )
}
