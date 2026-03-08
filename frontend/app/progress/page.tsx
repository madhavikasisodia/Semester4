"use client"

import { Navbar } from "@/components/navbar"
import { Card } from "@/components/ui/card"
import { useState, useEffect } from "react"
import { learningAPI, type ProgressStats, type ProgressHistory, type Achievement } from "@/lib/api"
import { 
  TrendingUp, 
  Trophy, 
  Clock, 
  Target,
  BookOpen,
  Brain,
  Flame,
  Award,
  AlertCircle
} from "lucide-react"
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell
} from "recharts"

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8']

// Helper function to format error messages
const formatErrorMessage = (err: any): string => {
  if (typeof err === 'string') return err
  
  if (Array.isArray(err.response?.data?.detail)) {
    return err.response.data.detail.map((e: any) => e.msg).join(', ')
  }
  
  if (typeof err.response?.data?.detail === 'string') {
    return err.response.data.detail
  }
  
  return err.message || "An error occurred"
}

export default function ProgressPage() {
  const [stats, setStats] = useState<ProgressStats | null>(null)
  const [history, setHistory] = useState<ProgressHistory[]>([])
  const [achievements, setAchievements] = useState<Achievement[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [timeRange, setTimeRange] = useState(30)

  useEffect(() => {
    fetchAllData()
  }, [timeRange])

  const fetchAllData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [statsData, historyData, achievementsData] = await Promise.all([
        learningAPI.getProgressStats(),
        learningAPI.getProgressHistory(timeRange),
        learningAPI.getAchievements()
      ])
      setStats(statsData)
      setHistory(historyData)
      setAchievements(achievementsData)
    } catch (err: any) {
      setError(formatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const prepareChartData = () => {
    return history.map(item => ({
      date: new Date(item.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      problems: item.problems_solved,
      tests: item.tests_taken,
      interviews: item.interviews_completed,
      timeSpent: item.time_spent_minutes
    }))
  }

  const prepareActivityData = () => {
    if (!stats) return []
    return [
      { name: 'Problems Solved', value: stats.total_problems_solved },
      { name: 'Tests Taken', value: stats.total_tests_taken },
      { name: 'Interviews', value: stats.total_interviews },
      { name: 'Achievements', value: stats.achievements_earned }
    ]
  }

  return (
    <div className="min-h-screen bg-background">
      <Navbar />
      
      <main className="container mx-auto px-4 py-8">
        <div className="max-w-7xl mx-auto space-y-8">
          {/* Header */}
          <div className="space-y-4">
            <h1 className="text-4xl font-bold">Learning Progress</h1>
            <p className="text-xl text-muted-foreground">
              Track your journey and celebrate your achievements
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <Card className="p-4 bg-destructive/10 border-destructive">
              <div className="flex items-center gap-2 text-destructive">
                <AlertCircle className="h-5 w-5" />
                <p>{error}</p>
              </div>
            </Card>
          )}

          {loading ? (
            <div className="grid md:grid-cols-4 gap-6">
              {[1, 2, 3, 4].map((i) => (
                <Card key={i} className="p-6 animate-pulse">
                  <div className="h-12 bg-gray-200 rounded"></div>
                </Card>
              ))}
            </div>
          ) : stats ? (
            <>
              {/* Stats Cards */}
              <div className="grid md:grid-cols-4 gap-6">
                <Card className="p-6 space-y-2">
                  <div className="flex items-center justify-between">
                    <Target className="h-8 w-8 text-blue-600" />
                    <span className="text-3xl font-bold">{stats.total_problems_solved}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">Problems Solved</p>
                </Card>

                <Card className="p-6 space-y-2">
                  <div className="flex items-center justify-between">
                    <Flame className="h-8 w-8 text-orange-600" />
                    <span className="text-3xl font-bold">{stats.current_streak}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">Day Streak</p>
                  <p className="text-xs text-muted-foreground">Best: {stats.longest_streak} days</p>
                </Card>

                <Card className="p-6 space-y-2">
                  <div className="flex items-center justify-between">
                    <Clock className="h-8 w-8 text-green-600" />
                    <span className="text-3xl font-bold">{stats.total_time_spent_hours.toFixed(1)}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">Hours Invested</p>
                </Card>

                <Card className="p-6 space-y-2">
                  <div className="flex items-center justify-between">
                    <Trophy className="h-8 w-8 text-yellow-600" />
                    <span className="text-3xl font-bold">{stats.achievements_earned}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">Achievements</p>
                </Card>
              </div>

              {/* Performance Metrics */}
              <div className="grid md:grid-cols-3 gap-6">
                <Card className="p-6 space-y-4">
                  <div className="flex items-center gap-2">
                    <BookOpen className="h-5 w-5 text-primary" />
                    <h3 className="font-semibold">Tests</h3>
                  </div>
                  <div>
                    <p className="text-3xl font-bold">{stats.total_tests_taken}</p>
                    <p className="text-sm text-muted-foreground">Total tests taken</p>
                  </div>
                  <div>
                    <p className="text-2xl font-semibold text-green-600">
                      {stats.avg_test_score.toFixed(1)}%
                    </p>
                    <p className="text-sm text-muted-foreground">Average score</p>
                  </div>
                </Card>

                <Card className="p-6 space-y-4">
                  <div className="flex items-center gap-2">
                    <Brain className="h-5 w-5 text-primary" />
                    <h3 className="font-semibold">Interviews</h3>
                  </div>
                  <div>
                    <p className="text-3xl font-bold">{stats.total_interviews}</p>
                    <p className="text-sm text-muted-foreground">Mock interviews completed</p>
                  </div>
                </Card>

                <Card className="p-6 space-y-4">
                  <div className="flex items-center gap-2">
                    <TrendingUp className="h-5 w-5 text-primary" />
                    <h3 className="font-semibold">Growth</h3>
                  </div>
                  <div>
                    <p className="text-3xl font-bold">{stats.total_problems_solved}</p>
                    <p className="text-sm text-muted-foreground">Total progress points</p>
                  </div>
                </Card>
              </div>

              {/* Charts */}
              <div className="grid md:grid-cols-2 gap-6">
                {/* Activity Over Time */}
                <Card className="p-6 space-y-4">
                  <h3 className="text-xl font-semibold">Activity Over Time</h3>
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={prepareChartData()}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="date" />
                      <YAxis />
                      <Tooltip />
                      <Legend />
                      <Line type="monotone" dataKey="problems" stroke="#8884d8" name="Problems" />
                      <Line type="monotone" dataKey="tests" stroke="#82ca9d" name="Tests" />
                      <Line type="monotone" dataKey="interviews" stroke="#ffc658" name="Interviews" />
                    </LineChart>
                  </ResponsiveContainer>
                </Card>

                {/* Activity Distribution */}
                <Card className="p-6 space-y-4">
                  <h3 className="text-xl font-semibold">Activity Distribution</h3>
                  <ResponsiveContainer width="100%" height={300}>
                    <PieChart>
                      <Pie
                        data={prepareActivityData()}
                        cx="50%"
                        cy="50%"
                        labelLine={false}
                        label={(entry) => `${entry.name}: ${entry.value}`}
                        outerRadius={80}
                        fill="#8884d8"
                        dataKey="value"
                      >
                        {prepareActivityData().map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </Card>
              </div>

              {/* Time Spent Chart */}
              <Card className="p-6 space-y-4">
                <h3 className="text-xl font-semibold">Time Invested (Minutes per Day)</h3>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={prepareChartData()}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="timeSpent" fill="#8884d8" name="Minutes" />
                  </BarChart>
                </ResponsiveContainer>
              </Card>

              {/* Achievements */}
              <Card className="p-6 space-y-4">
                <div className="flex items-center gap-2 mb-4">
                  <Award className="h-6 w-6 text-primary" />
                  <h3 className="text-xl font-semibold">Recent Achievements</h3>
                </div>
                
                {achievements.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <Trophy className="h-12 w-12 mx-auto mb-2 opacity-50" />
                    <p>No achievements yet. Keep learning to unlock them!</p>
                  </div>
                ) : (
                  <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {achievements.slice(0, 6).map((achievement) => (
                      <div
                        key={achievement.id}
                        className="p-4 border rounded-lg space-y-2 hover:bg-muted/50 transition-colors"
                      >
                        <div className="flex items-center gap-3">
                          <div className="text-3xl">{achievement.badge_icon}</div>
                          <div className="flex-1">
                            <h4 className="font-semibold">{achievement.title}</h4>
                            <p className="text-xs text-muted-foreground">
                              {achievement.description}
                            </p>
                          </div>
                        </div>
                        <div className="flex justify-between items-center text-sm">
                          <span className="text-muted-foreground">
                            {new Date(achievement.earned_date).toLocaleDateString()}
                          </span>
                          <span className="font-medium text-primary">
                            {achievement.points} pts
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </>
          ) : null}
        </div>
      </main>
    </div>
  )
}
