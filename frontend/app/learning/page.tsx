"use client"

import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { BookOpen, Sparkles, Filter } from "lucide-react"
import { useState } from "react"

const courses = [
  {
    id: 1,
    title: "Advanced JavaScript",
    description: "Master async/await, closures, and design patterns",
    progress: 65,
    difficulty: "Advanced",
    category: "Programming",
    lessons: 24,
    completed: 16,
  },
  {
    id: 2,
    title: "React Fundamentals",
    description: "Learn components, hooks, and state management",
    progress: 40,
    difficulty: "Intermediate",
    category: "Web Development",
    lessons: 18,
    completed: 7,
  },
  {
    id: 3,
    title: "Data Structures & Algorithms",
    description: "Essential algorithms and complexity analysis",
    progress: 85,
    difficulty: "Advanced",
    category: "Computer Science",
    lessons: 30,
    completed: 25,
  },
  {
    id: 4,
    title: "System Design",
    description: "Design scalable systems and architectures",
    progress: 20,
    difficulty: "Advanced",
    category: "Engineering",
    lessons: 20,
    completed: 4,
  },
]

export default function LearningPage() {
  const [selectedFilter, setSelectedFilter] = useState("all")

  const filters = ["all", "trending", "weak-topics", "new"]

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
            {/* Header */}
            <div className="space-y-4">
              <h1 className="text-4xl font-bold gradient-text">Personalized Learning</h1>
              <p className="text-muted-foreground max-w-2xl">
                AI-recommended courses tailored to your learning pace and goals
              </p>
            </div>

            {/* Filters */}
            <div className="flex flex-wrap gap-2">
              {filters.map((filter) => (
                <Button
                  key={filter}
                  variant={selectedFilter === filter ? "default" : "outline"}
                  size="sm"
                  onClick={() => setSelectedFilter(filter)}
                  className={
                    selectedFilter === filter ? "bg-gradient-to-r from-primary to-accent" : "border-primary/50"
                  }
                >
                  <Filter className="w-3 h-3 mr-2" />
                  {filter.charAt(0).toUpperCase() + filter.slice(1).replace("-", " ")}
                </Button>
              ))}
            </div>

            {/* Courses Grid */}
            <div className="grid md:grid-cols-2 gap-6">
              {courses.map((course) => (
                <Card key={course.id} className="glass p-6 group hover:bg-white/15 transition-all">
                  <div className="space-y-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <div className="p-2 rounded-lg bg-accent/20">
                            <BookOpen className="w-4 h-4 text-accent" />
                          </div>
                          <span className="text-xs font-semibold text-accent uppercase">{course.category}</span>
                        </div>
                        <h3 className="text-lg font-semibold">{course.title}</h3>
                        <p className="text-sm text-muted-foreground mt-1">{course.description}</p>
                      </div>
                      <span
                        className={`text-xs font-semibold px-2 py-1 rounded-full ${
                          course.difficulty === "Advanced"
                            ? "bg-red-500/20 text-red-300"
                            : course.difficulty === "Intermediate"
                              ? "bg-yellow-500/20 text-yellow-300"
                              : "bg-green-500/20 text-green-300"
                        }`}
                      >
                        {course.difficulty}
                      </span>
                    </div>

                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">
                          {course.completed} / {course.lessons} lessons
                        </span>
                        <span className="font-semibold gradient-text">{course.progress}%</span>
                      </div>
                      <Progress value={course.progress} className="h-2 bg-white/10" />
                    </div>

                    <div className="flex gap-2 pt-2">
                      <Button size="sm" className="flex-1 bg-gradient-to-r from-primary to-accent hover:opacity-90">
                        Continue Learning
                      </Button>
                      <Button size="sm" variant="outline" className="border-primary/50 bg-transparent">
                        <Sparkles className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </div>
        </div>
      </main>
    </>
  )
}
