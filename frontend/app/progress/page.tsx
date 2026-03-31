"use client"

// this page runs entirely on the client; uses React state and effects

// shared layout components
import { Navbar } from "@/components/navbar"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

// React hooks for component state management
import { useState, useEffect, useCallback } from "react"
import type { FormEvent } from "react"

// API helpers and type definitions for progress data
import {
  learningAPI,
  profileAPI,
  type ProgressStats,
  type ProgressHistory,
  type Achievement,
  type LeetCodeProfile,
  type GitHubProfile,
  type CodeChefProfile,
} from "@/lib/api"
import { normalizeGithubUsername } from "@/lib/utils"

// icons used in the progress dashboard
import { 
  TrendingUp, 
  Trophy, 
  Clock, 
  Target,
  BookOpen,
  Brain,
  Flame,
  Award,
  AlertCircle,
  Github,
  Code2,
  ChefHat
} from "lucide-react"

// charting components from recharts library
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

// colour palette for pie chart segments
const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8']

// utility to normalise error objects returned by axios/our API
// this ensures the UI can display a readable message regardless of format
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
  // component state
  const [stats, setStats] = useState<ProgressStats | null>(null) // aggregate numbers
  const [history, setHistory] = useState<ProgressHistory[]>([]) // daily timeline
  const [achievements, setAchievements] = useState<Achievement[]>([]) // recent badges
  const [loading, setLoading] = useState(true) // loading spinner
  const [error, setError] = useState<string | null>(null) // error banner
  const [timeRange, setTimeRange] = useState(30) // days of history to fetch
  const [leetcodeUsername, setLeetcodeUsername] = useState("")
  const [githubUsername, setGithubUsername] = useState("")
  const [leetcodeProfile, setLeetcodeProfile] = useState<LeetCodeProfile | null>(null)
  const [githubProfile, setGithubProfile] = useState<GitHubProfile | null>(null)
  const [codechefUsername, setCodechefUsername] = useState("")
  const [codechefProfile, setCodechefProfile] = useState<CodeChefProfile | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [profilesLastSynced, setProfilesLastSynced] = useState<string | null>(null)

  // refetch whenever timeRange changes (user picks 7/30/90 days)
  useEffect(() => {
    fetchAllData()
  }, [timeRange])

  // load all progress-related data in parallel
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

  const fetchExternalProfiles = useCallback(
    async (rawLeetcode: string, rawGithub: string, rawCodechef: string) => {
      const normalizedLeetcode = rawLeetcode.trim()
      const normalizedGithub = normalizeGithubUsername(rawGithub)
      const normalizedCodechef = rawCodechef.trim()

      if (!normalizedLeetcode || !normalizedGithub || !normalizedCodechef) {
        setProfileError("Please enter LeetCode, GitHub, and CodeChef usernames")
        return
      }

      setProfileLoading(true)
      setProfileError(null)
      try {
        const [combinedProfiles, codechefData] = await Promise.all([
          profileAPI.getCombinedProfile(normalizedLeetcode, normalizedGithub),
          profileAPI.getCodeChefProfile(normalizedCodechef),
        ])
        setLeetcodeProfile(combinedProfiles.leetcode)
        setGithubProfile(combinedProfiles.github)
        setCodechefProfile(codechefData)
        if (typeof window !== "undefined") {
          localStorage.setItem("leetcode_username", normalizedLeetcode)
          localStorage.setItem("github_username", normalizedGithub)
          localStorage.setItem("codechef_username", normalizedCodechef)
        }
        setProfilesLastSynced(new Date().toISOString())
        setLeetcodeUsername(normalizedLeetcode)
        setGithubUsername(normalizedGithub)
        setCodechefUsername(normalizedCodechef)
      } catch (err: any) {
        setProfileError(formatErrorMessage(err))
        setCodechefProfile(null)
      } finally {
        setProfileLoading(false)
      }
    },
    []
  )

  useEffect(() => {
    if (typeof window === "undefined") return
    const savedLeetcode = localStorage.getItem("leetcode_username") || ""
    const savedGithubRaw = localStorage.getItem("github_username") || ""
    const savedGithub = normalizeGithubUsername(savedGithubRaw)
    const savedCodechef = (localStorage.getItem("codechef_username") || "").trim()

    if (savedLeetcode) {
      setLeetcodeUsername(savedLeetcode)
    }
    if (savedGithub) {
      setGithubUsername(savedGithub)
    }
    if (savedCodechef) {
      setCodechefUsername(savedCodechef)
    }
    if (savedLeetcode && savedGithub && savedCodechef) {
      fetchExternalProfiles(savedLeetcode, savedGithub, savedCodechef)
    }
  }, [fetchExternalProfiles])

  // transform raw history into shape expected by recharts components
  const prepareChartData = () => {
    return history.map(item => ({
      date: new Date(item.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      problems: item.problems_solved,
      tests: item.tests_taken,
      interviews: item.interviews_completed,
      timeSpent: item.time_spent_minutes
    }))
  }

  // build data array for pie chart summarising activity counts
  const prepareActivityData = () => {
    if (!stats) return []
    return [
      { name: 'Problems Solved', value: stats.total_problems_solved },
      { name: 'Tests Taken', value: stats.total_tests_taken },
      { name: 'Interviews', value: stats.total_interviews },
      { name: 'Achievements', value: stats.achievements_earned }
    ]
  }

  const handleProfileSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    fetchExternalProfiles(leetcodeUsername, githubUsername, codechefUsername)
  }

  const formatNumber = (value?: number | null) =>
    typeof value === 'number' ? value.toLocaleString() : '—'

  const formatPercent = (value?: number | null) =>
    typeof value === 'number' ? `${value.toFixed(1)}%` : '—'

  const formatRank = (value?: number | null) =>
    typeof value === 'number' ? `#${value.toLocaleString()}` : '—'

  const formatRatingWithDate = (value?: number | null, date?: string | null) => {
    const ratingText = formatNumber(value)
    if (ratingText === '—' || !date) return ratingText
    return `${ratingText} (${date})`
  }

  return (
    <div className="min-h-screen bg-background">
      <Navbar />
      
      <main className="container mx-auto px-4 pt-24 pb-8">
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

              {/* External Coding Profiles */}
              <div className="space-y-4">
                <Card className="p-6 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <div>
                      <p className="text-sm text-muted-foreground">Bring in live platform metrics</p>
                      <h3 className="text-xl font-semibold">Sync LeetCode & GitHub</h3>
                    </div>
                    {profilesLastSynced && (
                      <span className="text-sm text-muted-foreground">
                        Last synced {new Date(profilesLastSynced).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    )}
                  </div>

                  <form
                    onSubmit={handleProfileSubmit}
                    className="grid gap-4 md:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_auto]"
                  >
                    <div>
                      <Label htmlFor="progress-leetcode">LeetCode username</Label>
                      <Input
                        id="progress-leetcode"
                        placeholder="leetcode-handle"
                        value={leetcodeUsername}
                        onChange={(event) => setLeetcodeUsername(event.target.value)}
                      />
                    </div>
                    <div>
                      <Label htmlFor="progress-github">GitHub username</Label>
                      <Input
                        id="progress-github"
                        placeholder="github-handle"
                        value={githubUsername}
                        onChange={(event) => setGithubUsername(event.target.value)}
                      />
                    </div>
                    <div>
                      <Label htmlFor="progress-codechef">CodeChef username</Label>
                      <Input
                        id="progress-codechef"
                        placeholder="codechef-handle"
                        value={codechefUsername}
                        onChange={(event) => setCodechefUsername(event.target.value)}
                      />
                    </div>
                    <Button type="submit" disabled={profileLoading} className="self-end h-12">
                      {profileLoading ? "Syncing..." : "Sync profiles"}
                    </Button>
                  </form>

                  {profileError && (
                    <div className="flex items-center gap-2 text-sm text-destructive">
                      <AlertCircle className="h-4 w-4" />
                      <span>{profileError}</span>
                    </div>
                  )}
                </Card>

                <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
                  <Card className="p-6 space-y-6">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-full bg-primary/10 text-primary">
                        <Code2 className="h-5 w-5" />
                      </div>
                      <div>
                        <h3 className="text-lg font-semibold">LeetCode Activity</h3>
                        <p className="text-sm text-muted-foreground">
                          {leetcodeProfile ? `@${leetcodeProfile.username}` : "Waiting for connection"}
                        </p>
                      </div>
                    </div>

                    {leetcodeProfile ? (
                      <div className="grid grid-cols-2 gap-4 text-sm">
                        <div>
                          <p className="text-xs text-muted-foreground">Total solved</p>
                          <p className="text-2xl font-bold">{formatNumber(leetcodeProfile.total_solved)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Acceptance rate</p>
                          <p className="text-2xl font-bold">{formatPercent(leetcodeProfile.acceptance_rate)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Easy / Medium / Hard</p>
                          <p className="text-lg font-semibold">
                            {formatNumber(leetcodeProfile.easy_solved)} / {formatNumber(leetcodeProfile.medium_solved)} / {formatNumber(leetcodeProfile.hard_solved)}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Ranking</p>
                          <p className="text-lg font-semibold">{formatNumber(leetcodeProfile.ranking)}</p>
                        </div>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Connect your LeetCode handle to compare live solved counts with your study streak.
                      </p>
                    )}
                  </Card>

                  <Card className="p-6 space-y-6">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-full bg-muted text-foreground">
                        <Github className="h-5 w-5" />
                      </div>
                      <div>
                        <h3 className="text-lg font-semibold">GitHub Activity</h3>
                        <p className="text-sm text-muted-foreground">
                          {githubProfile ? `@${githubProfile.username}` : "Waiting for connection"}
                        </p>
                      </div>
                    </div>

                    {githubProfile ? (
                      <div className="grid grid-cols-2 gap-4 text-sm">
                        <div>
                          <p className="text-xs text-muted-foreground">Public repos</p>
                          <p className="text-2xl font-bold">{formatNumber(githubProfile.public_repos)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Followers</p>
                          <p className="text-2xl font-bold">{formatNumber(githubProfile.followers)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Following</p>
                          <p className="text-lg font-semibold">{formatNumber(githubProfile.following)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Joined</p>
                          <p className="text-lg font-semibold">
                            {githubProfile.created_at ? new Date(githubProfile.created_at).toLocaleDateString() : "—"}
                          </p>
                        </div>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Connect your GitHub handle to see repository momentum alongside your learning metrics.
                      </p>
                    )}
                  </Card>

                  <Card className="p-6 space-y-6">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-full bg-secondary/10 text-secondary-foreground">
                        <ChefHat className="h-5 w-5" />
                      </div>
                      <div>
                        <h3 className="text-lg font-semibold">CodeChef Activity</h3>
                        <p className="text-sm text-muted-foreground">
                          {codechefProfile ? `@${codechefProfile.username}` : "Waiting for connection"}
                        </p>
                      </div>
                    </div>

                    {codechefProfile ? (
                      <div className="grid grid-cols-2 gap-4 text-sm">
                        <div>
                          <p className="text-xs text-muted-foreground">Current rating</p>
                          <p className="text-2xl font-bold">{formatNumber(codechefProfile.rating)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Stars</p>
                          <p className="text-lg font-semibold">{codechefProfile.stars || "—"}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Highest rating</p>
                          <p className="text-lg font-semibold">
                            {formatRatingWithDate(
                              codechefProfile.highest_rating,
                              codechefProfile.highest_rating_time ?? null
                            )}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Global / Country rank</p>
                          <p className="text-lg font-semibold">
                            {formatRank(codechefProfile.global_rank)} / {formatRank(codechefProfile.country_rank)}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Fully solved</p>
                          <p className="text-lg font-semibold">{formatNumber(codechefProfile.fully_solved)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Partially solved</p>
                          <p className="text-lg font-semibold">{formatNumber(codechefProfile.partially_solved)}</p>
                        </div>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Connect your CodeChef handle to compare contest ratings with your learning stats.
                      </p>
                    )}
                  </Card>
                </div>
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
