"use client"

import { Navbar } from "@/components/navbar"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts"
import { Users, BookOpen, BarChart3, TrendingUp } from "lucide-react"

const userData = [
  { name: "Week 1", users: 120, active: 80 },
  { name: "Week 2", users: 180, active: 140 },
  { name: "Week 3", users: 250, active: 190 },
  { name: "Week 4", users: 320, active: 260 },
]

const courseStats = [
  { name: "JavaScript", value: 35 },
  { name: "React", value: 25 },
  { name: "Python", value: 20 },
  { name: "Other", value: 20 },
]

const COLORS = ["oklch(0.60 0.25 280)", "oklch(0.65 0.28 270)", "oklch(0.50 0.30 260)", "oklch(0.55 0.25 300)"]

export default function AdminPage() {
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
            <div className="space-y-2">
              <h1 className="text-4xl font-bold gradient-text">Admin Dashboard</h1>
              <p className="text-muted-foreground">Platform analytics and management</p>
            </div>

            {/* Stats Cards */}
            <div className="grid md:grid-cols-4 gap-6">
              {[
                { icon: Users, label: "Total Users", value: "1,234" },
                { icon: BookOpen, label: "Active Courses", value: "42" },
                { icon: BarChart3, label: "Quizzes Taken", value: "5,678" },
                { icon: TrendingUp, label: "Avg. Score", value: "82%" },
              ].map((stat, i) => (
                <Card key={i} className="glass p-6">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-sm text-muted-foreground">{stat.label}</p>
                      <p className="text-2xl font-bold gradient-text mt-2">{stat.value}</p>
                    </div>
                    <stat.icon className="w-8 h-8 text-accent opacity-50" />
                  </div>
                </Card>
              ))}
            </div>

            {/* Charts */}
            <div className="grid lg:grid-cols-2 gap-6">
              <Card className="glass p-6">
                <h2 className="text-lg font-semibold mb-4">User Growth</h2>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={userData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                    <XAxis stroke="rgba(255,255,255,0.5)" />
                    <YAxis stroke="rgba(255,255,255,0.5)" />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "rgba(12,12,30,0.8)",
                        border: "1px solid rgba(255,255,255,0.2)",
                      }}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="users" stroke="oklch(0.60 0.25 280)" />
                    <Line type="monotone" dataKey="active" stroke="oklch(0.65 0.28 270)" />
                  </LineChart>
                </ResponsiveContainer>
              </Card>

              <Card className="glass p-6">
                <h2 className="text-lg font-semibold mb-4">Course Distribution</h2>
                <ResponsiveContainer width="100%" height={300}>
                  <PieChart>
                    <Pie
                      data={courseStats}
                      cx="50%"
                      cy="50%"
                      labelLine={false}
                      label={({ name, value }) => `${name}: ${value}%`}
                      outerRadius={80}
                      fill="#8884d8"
                      dataKey="value"
                    >
                      {courseStats.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </Card>
            </div>

            {/* Management Section */}
            <Card className="glass p-6">
              <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
              <div className="grid md:grid-cols-3 gap-4">
                <Button
                  variant="outline"
                  className="border-primary/50 text-foreground hover:bg-primary/10 bg-transparent"
                >
                  Manage Courses
                </Button>
                <Button
                  variant="outline"
                  className="border-primary/50 text-foreground hover:bg-primary/10 bg-transparent"
                >
                  Manage Questions
                </Button>
                <Button
                  variant="outline"
                  className="border-primary/50 text-foreground hover:bg-primary/10 bg-transparent"
                >
                  View Reports
                </Button>
              </div>
            </Card>
          </div>
        </div>
      </main>
    </>
  )
}
