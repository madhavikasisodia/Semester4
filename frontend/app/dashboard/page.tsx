"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { Navbar } from "@/components/navbar"
import { useAuthStore } from "@/lib/store"
import { ProgressCard } from "@/components/progress-card"
import { Card } from "@/components/ui/card"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
} from "recharts"
import { BookOpen, Brain, Target, ArrowRight, TrendingUp, Github, Code, Trophy, Star, Users, Upload, FileText, Award, CheckCircle, AlertCircle } from "lucide-react"
import Link from "next/link"
import {
  profileAPI,
  type CombinedProfile,
  resumeAPI,
  certificateAPI,
  learningAPI,
  type ProgressHistory,
  type ProgressStats,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { normalizeGithubUsername } from "@/lib/utils"

type DashboardOverview = Awaited<ReturnType<typeof learningAPI.getDashboardOverview>>

const formatApiError = (err: any): string => {
  if (!err) return "Something went wrong"
  if (typeof err === "string") return err
  if (Array.isArray(err.response?.data?.detail)) {
    return err.response.data.detail.map((item: any) => item.msg).join(", ")
  }
  if (typeof err.response?.data?.detail === "string") {
    return err.response.data.detail
  }
  return err.message || "Something went wrong"
}

export default function Dashboard() {
  const router = useRouter()
  const { user } = useAuthStore()
  
  // State for profile data
  const [profileData, setProfileData] = useState<CombinedProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [profileError, setProfileError] = useState<string | null>(null)
  
  // State for profile usernames
  const [leetcodeUsername, setLeetcodeUsername] = useState("")
  const [githubUsername, setGithubUsername] = useState("")
  const [showProfileInput, setShowProfileInput] = useState(false)

  // Dashboard metrics
  const [dashboardOverview, setDashboardOverview] = useState<DashboardOverview | null>(null)
  const [progressHistory, setProgressHistory] = useState<ProgressHistory[]>([])
  const [metricsLoading, setMetricsLoading] = useState(true)
  const [metricsError, setMetricsError] = useState<string | null>(null)
  const [enterAnimationReady, setEnterAnimationReady] = useState(false)

  // Resume/Certificate upload states
  const [resumeFile, setResumeFile] = useState<File | null>(null)
  const [resumeUploading, setResumeUploading] = useState(false)
  const [resumeSuccess, setResumeSuccess] = useState<string | null>(null)
  const [resumeError, setResumeError] = useState<string | null>(null)
  
  const [certFile, setCertFile] = useState<File | null>(null)
  const [certTitle, setCertTitle] = useState("")
  const [certIssuedBy, setCertIssuedBy] = useState("")
  const [certIssueDate, setCertIssueDate] = useState("")
  const [certUploading, setCertUploading] = useState(false)
  const [certSuccess, setCertSuccess] = useState<string | null>(null)
  const [certError, setCertError] = useState<string | null>(null)

  const progressStats: ProgressStats | null = dashboardOverview?.progress_stats ?? null

  const activityChartData = useMemo(() => {
    return progressHistory.map((record) => ({
      date: new Date(record.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      problems: record.problems_solved,
      tests: record.tests_taken,
      interviews: record.interviews_completed,
    }))
  }, [progressHistory])

  const skillRadarData = useMemo(() => {
    const counts: Record<string, number> = {}
    progressHistory.forEach((record) => {
      record.skills_practiced?.forEach((skill) => {
        counts[skill] = (counts[skill] || 0) + 1
      })
    })
    const maxCount = Object.values(counts).reduce((max, count) => Math.max(max, count), 0)
    if (maxCount === 0) return []
    return Object.entries(counts).map(([skill, count]) => ({
      skill,
      value: Math.round((count / maxCount) * 100),
    }))
  }, [progressHistory])

  const totalTrackedDays = progressHistory.length

  const { learningProgressPercent, interviewReadinessPercent } = useMemo(() => {
    if (!progressStats || progressHistory.length === 0) {
      return { learningProgressPercent: 0, interviewReadinessPercent: 0 }
    }

    let maxProblemsPerDay = 0
    let maxInterviewsPerDay = 0
    progressHistory.forEach((record) => {
      maxProblemsPerDay = Math.max(maxProblemsPerDay, record.problems_solved)
      maxInterviewsPerDay = Math.max(maxInterviewsPerDay, record.interviews_completed)
    })

    const problemCapPerDay = Math.max(1, maxProblemsPerDay)
    const interviewCapPerDay = Math.max(1, maxInterviewsPerDay)
    const problemDenominator = problemCapPerDay * progressHistory.length
    const interviewDenominator = interviewCapPerDay * progressHistory.length

    return {
      learningProgressPercent: Math.min(
        100,
        Math.max(0, Math.round((progressStats.total_problems_solved / Math.max(1, problemDenominator)) * 100))
      ),
      interviewReadinessPercent: Math.min(
        100,
        Math.max(0, Math.round((progressStats.total_interviews / Math.max(1, interviewDenominator)) * 100))
      ),
    }
  }, [progressStats, progressHistory])

  const quizAccuracyPercent = progressStats ? Math.min(100, Math.max(0, Math.round(progressStats.avg_test_score))) : 0
  const hasActivityData = activityChartData.length > 0
  const hasSkillData = skillRadarData.length > 0

  useEffect(() => {
    if (!user) {
      router.push("/login")
    }
  }, [user, router])

  useEffect(() => {
    const frame = requestAnimationFrame(() => setEnterAnimationReady(true))
    return () => cancelAnimationFrame(frame)
  }, [])

  useEffect(() => {
    if (!user) return

    let isMounted = true

    const fetchDashboardData = async () => {
      setMetricsLoading(true)
      setMetricsError(null)
      try {
        const [overviewData, historyData] = await Promise.all([
          learningAPI.getDashboardOverview(),
          learningAPI.getProgressHistory(30),
        ])
        if (!isMounted) return
        setDashboardOverview(overviewData)
        setProgressHistory(historyData)
      } catch (err) {
        if (!isMounted) return
        setMetricsError(formatApiError(err))
      } finally {
        if (!isMounted) return
        setMetricsLoading(false)
      }
    }

    fetchDashboardData()

    return () => {
      isMounted = false
    }
  }, [user])

  const fetchProfile = async () => {
    const normalizedLeetcode = leetcodeUsername.trim()
    const normalizedGithub = normalizeGithubUsername(githubUsername)

    if (!normalizedLeetcode || !normalizedGithub) {
      setProfileError("Please enter both LeetCode and GitHub usernames")
      return
    }

    setLoading(true)
    setProfileError(null)

    try {
      const data = await profileAPI.getCombinedProfile(normalizedLeetcode, normalizedGithub)
      setProfileData(data)
      setLeetcodeUsername(normalizedLeetcode)
      setGithubUsername(normalizedGithub)
      setShowProfileInput(false)
      // Store usernames in localStorage for persistence
      localStorage.setItem("leetcode_username", normalizedLeetcode)
      localStorage.setItem("github_username", normalizedGithub)
    } catch (err: any) {
      setProfileError(err.response?.data?.detail || "Failed to fetch profile data")
    } finally {
      setLoading(false)
    }
  }

  // Load saved usernames on mount
  useEffect(() => {
    const savedLeetcode = localStorage.getItem("leetcode_username")
    const savedGithubRaw = localStorage.getItem("github_username")
    const savedGithub = savedGithubRaw ? normalizeGithubUsername(savedGithubRaw) : ""
    
    if (savedLeetcode && savedGithub) {
      setLeetcodeUsername(savedLeetcode)
      setGithubUsername(savedGithub)
      // Auto-fetch profile if usernames are saved
      profileAPI.getCombinedProfile(savedLeetcode, savedGithub)
        .then(setProfileData)
        .catch(() => setShowProfileInput(true))
    } else {
      setShowProfileInput(true)
    }
  }, [])

  const handleResumeUpload = async () => {
    if (!resumeFile) {
      setResumeError("Please select a PDF file")
      return
    }

    setResumeUploading(true)
    setResumeError(null)
    setResumeSuccess(null)

    try {
      const result = await resumeAPI.uploadResume(resumeFile)
      setResumeSuccess(`${result.message} Analyzing...`)
      
      // Auto-analyze after upload
      setTimeout(async () => {
        try {
          await resumeAPI.analyzeResume(result.id)
          setResumeSuccess("Resume uploaded and analyzed successfully! ✓")
          setResumeFile(null)
        } catch (err: any) {
          setResumeError("Uploaded but analysis failed: " + (err.response?.data?.detail || err.message))
        }
      }, 1000)
    } catch (err: any) {
      setResumeError(err.response?.data?.detail || "Failed to upload resume")
    } finally {
      setResumeUploading(false)
    }
  }

  const handleCertificateUpload = async () => {
    if (!certFile || !certTitle || !certIssuedBy || !certIssueDate) {
      setCertError("Please fill all fields and select a file")
      return
    }

    setCertUploading(true)
    setCertError(null)
    setCertSuccess(null)

    try {
      const result = await certificateAPI.uploadCertificate(
        certFile,
        certTitle,
        certIssuedBy,
        certIssueDate
      )
      setCertSuccess(`Certificate uploaded successfully! ✓`)
      setCertFile(null)
      setCertTitle("")
      setCertIssuedBy("")
      setCertIssueDate("")
    } catch (err: any) {
      setCertError(err.response?.data?.detail || err.message || "Failed to upload certificate")
    } finally {
      setCertUploading(false)
    }
  }

  if (!user) return null

  return (
    <>
      <Navbar />
      <main className="pt-20 pb-12">
        <div className="min-h-screen relative">
          <div className="absolute inset-0 -z-10">
            <div className="absolute top-20 left-10 w-72 h-72 bg-primary/10 rounded-full blur-3xl opacity-20" />
            <div className="absolute bottom-20 right-10 w-72 h-72 bg-accent/10 rounded-full blur-3xl opacity-20" />
          </div>

          <div
            className={`max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-8 transform transition-all duration-700 ease-out ${enterAnimationReady ? "opacity-100 translate-y-0" : "opacity-0 translate-y-6"}`}
          >
            {/* Header */}
            <div className="space-y-2">
              <h1 className="text-4xl font-bold gradient-text">Welcome back, {user.name}! 👋</h1>
              <p className="text-muted-foreground">Track your progress and continue learning</p>
            </div>

            {/* Quick Links */}
            <div className="grid md:grid-cols-4 gap-4">
              <Link href="/recommendations">
                <Card className="glass p-6 hover:bg-white/10 transition-all cursor-pointer h-full">
                  <div className="flex items-center gap-3">
                    <BookOpen className="w-8 h-8 text-primary" />
                    <div>
                      <h3 className="font-semibold">AI Recommendations</h3>
                      <p className="text-sm text-muted-foreground">Personalized learning</p>
                    </div>
                  </div>
                </Card>
              </Link>

              <Link href="/progress">
                <Card className="glass p-6 hover:bg-white/10 transition-all cursor-pointer h-full">
                  <div className="flex items-center gap-3">
                    <TrendingUp className="w-8 h-8 text-accent" />
                    <div>
                      <h3 className="font-semibold">Progress Tracker</h3>
                      <p className="text-sm text-muted-foreground">View analytics</p>
                    </div>
                  </div>
                </Card>
              </Link>

              <Link href="/interview">
                <Card className="glass p-6 hover:bg-white/10 transition-all cursor-pointer h-full">
                  <div className="flex items-center gap-3">
                    <Brain className="w-8 h-8 text-green-500" />
                    <div>
                      <h3 className="font-semibold">Mock Interview</h3>
                      <p className="text-sm text-muted-foreground">Practice with AI</p>
                    </div>
                  </div>
                </Card>
              </Link>

              <Link href="/quiz">
                <Card className="glass p-6 hover:bg-white/10 transition-all cursor-pointer h-full">
                  <div className="flex items-center gap-3">
                    <Target className="w-8 h-8 text-yellow-500" />
                    <div>
                      <h3 className="font-semibold">Take Tests</h3>
                      <p className="text-sm text-muted-foreground">Test your skills</p>
                    </div>
                  </div>
                </Card>
              </Link>
            </div>

            {/* Profile Integration Section */}
            {showProfileInput && (
              <div className="space-y-6">
                <Card className="glass p-6">
                  <h2 className="text-2xl font-semibold mb-2 gradient-text">Connect Your Profile</h2>
                  <p className="text-muted-foreground mb-6">
                    Link your coding profiles and upload your resume to get personalized AI recommendations
                  </p>
                  
                  {/* Coding Profiles */}
                  <div className="mb-8">
                    <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                      <Code className="w-5 h-5 text-primary" />
                      Coding Profiles
                    </h3>
                    <div className="grid md:grid-cols-2 gap-4 mb-4">
                      <div>
                        <Label htmlFor="leetcode" className="text-sm font-medium mb-2 block">
                          LeetCode Username
                        </Label>
                        <Input
                          id="leetcode"
                          placeholder="your-leetcode-username"
                          value={leetcodeUsername}
                          onChange={(e) => setLeetcodeUsername(e.target.value)}
                          className="glass"
                        />
                      </div>
                      <div>
                        <Label htmlFor="github" className="text-sm font-medium mb-2 block">
                          GitHub Username
                        </Label>
                        <Input
                          id="github"
                          placeholder="your-github-username"
                          value={githubUsername}
                          onChange={(e) => setGithubUsername(e.target.value)}
                          className="glass"
                        />
                      </div>
                    </div>
                    {profileError && <p className="text-red-500 text-sm mb-4">{profileError}</p>}
                    <Button onClick={fetchProfile} disabled={loading} className="w-full md:w-auto">
                      {loading ? "Loading..." : "Connect Coding Profiles"}
                    </Button>
                  </div>

                  <div className="h-px bg-white/10 my-8"></div>

                  {/* Resume Upload */}
                  <div className="mb-8">
                    <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                      <FileText className="w-5 h-5 text-accent" />
                      Upload Resume
                    </h3>
                    <p className="text-sm text-muted-foreground mb-4">
                      Upload your resume (PDF only) for AI-powered analysis and personalized recommendations
                    </p>
                    <div className="space-y-4">
                      <div className="flex items-center gap-4">
                        <Input
                          type="file"
                          accept=".pdf"
                          onChange={(e) => setResumeFile(e.target.files?.[0] || null)}
                          className="glass flex-1"
                        />
                        <Button
                          onClick={handleResumeUpload}
                          disabled={!resumeFile || resumeUploading}
                          className="flex items-center gap-2"
                        >
                          <Upload className="w-4 h-4" />
                          {resumeUploading ? "Uploading..." : "Upload Resume"}
                        </Button>
                      </div>
                      {resumeSuccess && (
                        <p className="text-green-500 text-sm flex items-center gap-2">
                          <CheckCircle className="w-4 h-4" />
                          {resumeSuccess}
                        </p>
                      )}
                      {resumeError && <p className="text-red-500 text-sm">{resumeError}</p>}
                      {resumeFile && (
                        <p className="text-sm text-muted-foreground">
                          Selected: {resumeFile.name} ({(resumeFile.size / 1024).toFixed(2)} KB)
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="h-px bg-white/10 my-8"></div>

                  {/* Certificate Upload */}
                  <div>
                    <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                      <Award className="w-5 h-5 text-secondary" />
                      Upload Certificate
                    </h3>
                    <p className="text-sm text-muted-foreground mb-4">
                      Upload your certifications to showcase your achievements
                    </p>
                    <div className="space-y-4">
                      <div className="grid md:grid-cols-2 gap-4">
                        <div>
                          <Label htmlFor="cert-title" className="text-sm font-medium mb-2 block">
                            Certificate Title *
                          </Label>
                          <Input
                            id="cert-title"
                            placeholder="AWS Certified Solutions Architect"
                            value={certTitle}
                            onChange={(e) => setCertTitle(e.target.value)}
                            className="glass"
                          />
                        </div>
                        <div>
                          <Label htmlFor="cert-issued" className="text-sm font-medium mb-2 block">
                            Issued By *
                          </Label>
                          <Input
                            id="cert-issued"
                            placeholder="Amazon Web Services"
                            value={certIssuedBy}
                            onChange={(e) => setCertIssuedBy(e.target.value)}
                            className="glass"
                          />
                        </div>
                      </div>
                      <div>
                        <Label htmlFor="cert-date" className="text-sm font-medium mb-2 block">
                          Issue Date *
                        </Label>
                        <Input
                          id="cert-date"
                          type="date"
                          value={certIssueDate}
                          onChange={(e) => setCertIssueDate(e.target.value)}
                          className="glass"
                        />
                      </div>
                      <div className="flex items-center gap-4">
                        <Input
                          type="file"
                          accept=".pdf,.jpg,.jpeg,.png"
                          onChange={(e) => setCertFile(e.target.files?.[0] || null)}
                          className="glass flex-1"
                        />
                        <Button
                          onClick={handleCertificateUpload}
                          disabled={!certFile || !certTitle || !certIssuedBy || !certIssueDate || certUploading}
                          className="flex items-center gap-2"
                        >
                          <Upload className="w-4 h-4" />
                          {certUploading ? "Uploading..." : "Upload Certificate"}
                        </Button>
                      </div>
                      {certSuccess && (
                        <p className="text-green-500 text-sm flex items-center gap-2">
                          <CheckCircle className="w-4 h-4" />
                          {certSuccess}
                        </p>
                      )}
                      {certError && <p className="text-red-500 text-sm">{certError}</p>}
                      {certFile && (
                        <p className="text-sm text-muted-foreground">
                          Selected: {certFile.name} ({(certFile.size / 1024).toFixed(2)} KB)
                        </p>
                      )}
                    </div>
                  </div>
                </Card>
              </div>
            )}

            {/* Profile Stats Display */}
            {profileData && (
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-2xl font-bold">Your Coding Profile</h2>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowProfileInput(true)}
                    className="glass"
                  >
                    Update Profiles
                  </Button>
                </div>

                <div className="grid md:grid-cols-2 gap-6">
                  {/* LeetCode Stats */}
                  <Card className="glass p-6">
                    <div className="flex items-center gap-3 mb-4">
                      <Code className="w-8 h-8 text-primary" />
                      <div>
                        <h3 className="text-lg font-semibold">LeetCode Profile</h3>
                        <p className="text-sm text-muted-foreground">@{profileData.leetcode.username}</p>
                      </div>
                    </div>
                    <div className="space-y-4">
                      {profileData.leetcode.ranking && (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Trophy className="w-4 h-4 text-primary" />
                          <span>Rank: {profileData.leetcode.ranking.toLocaleString()}</span>
                        </div>
                      )}
                      <div className="grid grid-cols-3 gap-2">
                        <div className="bg-white/5 rounded-lg p-3 text-center">
                          <p className="text-2xl font-bold text-green-500">
                            {profileData.leetcode.easy_solved || 0}
                          </p>
                          <p className="text-xs text-muted-foreground">Easy</p>
                        </div>
                        <div className="bg-white/5 rounded-lg p-3 text-center">
                          <p className="text-2xl font-bold text-yellow-500">
                            {profileData.leetcode.medium_solved || 0}
                          </p>
                          <p className="text-xs text-muted-foreground">Medium</p>
                        </div>
                        <div className="bg-white/5 rounded-lg p-3 text-center">
                          <p className="text-2xl font-bold text-red-500">
                            {profileData.leetcode.hard_solved || 0}
                          </p>
                          <p className="text-xs text-muted-foreground">Hard</p>
                        </div>
                      </div>
                      {profileData.leetcode.total_solved !== undefined && (
                        <div className="text-center pt-2 border-t border-white/10">
                          <p className="text-sm text-muted-foreground">Total Problems Solved</p>
                          <p className="text-3xl font-bold gradient-text">
                            {profileData.leetcode.total_solved}
                          </p>
                        </div>
                      )}
                    </div>
                  </Card>

                  {/* GitHub Stats */}
                  <Card className="glass p-6">
                    <div className="flex items-center gap-3 mb-4">
                      <Github className="w-8 h-8 text-accent" />
                      <div>
                        <h3 className="text-lg font-semibold">GitHub Profile</h3>
                        <p className="text-sm text-muted-foreground">@{profileData.github.username}</p>
                      </div>
                    </div>
                    <div className="space-y-4">
                      {(profileData.github.avatar_url || profileData.github.name || profileData.github.bio) && (
                        <div className="flex items-center gap-3">
                          {profileData.github.avatar_url && (
                            <img
                              src={profileData.github.avatar_url}
                              alt="avatar"
                              className="w-12 h-12 rounded-full"
                            />
                          )}
                          <div>
                            {profileData.github.name && (
                              <p className="font-medium">{profileData.github.name}</p>
                            )}
                            {profileData.github.bio && (
                              <p className="text-sm text-muted-foreground">{profileData.github.bio}</p>
                            )}
                          </div>
                        </div>
                      )}
                      <div className="grid grid-cols-3 gap-2">
                        <div className="bg-white/5 rounded-lg p-3 text-center">
                          <p className="text-2xl font-bold">{profileData.github.public_repos || 0}</p>
                          <p className="text-xs text-muted-foreground">Repos</p>
                        </div>
                        <div className="bg-white/5 rounded-lg p-3 text-center">
                          <p className="text-2xl font-bold">{profileData.github.followers || 0}</p>
                          <p className="text-xs text-muted-foreground flex items-center justify-center gap-1">
                            <Users className="w-3 h-3" />
                            Followers
                          </p>
                        </div>
                        <div className="bg-white/5 rounded-lg p-3 text-center">
                          <p className="text-2xl font-bold">{profileData.github.following || 0}</p>
                          <p className="text-xs text-muted-foreground">Following</p>
                        </div>
                      </div>
                    </div>
                  </Card>
                </div>

                {/* Combined Stats */}
                <Card className="glass p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <Star className="w-8 h-8 text-secondary" />
                    <h3 className="text-lg font-semibold">Combined Achievement Score</h3>
                  </div>
                  <div className="grid md:grid-cols-4 gap-4">
                    <div className="text-center">
                      <p className="text-3xl font-bold text-primary">
                        {profileData.leetcode.total_solved || 0}
                      </p>
                      <p className="text-sm text-muted-foreground">Problems Solved</p>
                    </div>
                    <div className="text-center">
                      <p className="text-3xl font-bold text-accent">
                        {profileData.github.public_repos || 0}
                      </p>
                      <p className="text-sm text-muted-foreground">Total Repos</p>
                    </div>
                    <div className="text-center">
                      <p className="text-3xl font-bold text-secondary">
                        {profileData.github.followers || 0}
                      </p>
                      <p className="text-sm text-muted-foreground">Total Followers</p>
                    </div>
                    <div className="text-center">
                      <p className="text-3xl font-bold gradient-text">
                        {Math.round(
                          (profileData.leetcode.total_solved || 0) * 10 +
                          (profileData.github.public_repos || 0) * 5 +
                          (profileData.github.followers || 0) * 2
                        )}
                      </p>
                      <p className="text-sm text-muted-foreground">Combined Score</p>
                    </div>
                  </div>
                </Card>
              </div>
            )}

            {metricsError && (
              <Card className="p-4 border-destructive bg-destructive/10">
                <div className="flex items-center gap-2 text-destructive">
                  <AlertCircle className="w-5 h-5" />
                  <p>{metricsError}</p>
                </div>
              </Card>
            )}

            {/* Quick Stats */}
            <div className="grid md:grid-cols-3 gap-6">
              {metricsLoading ? (
                Array.from({ length: 3 }).map((_, index) => (
                  <Card key={`metric-skeleton-${index}`} className="p-6 space-y-4 animate-pulse">
                    <div className="h-4 bg-white/10 rounded w-1/2" />
                    <div className="h-3 bg-white/10 rounded w-1/3" />
                    <div className="h-6 bg-white/10 rounded" />
                  </Card>
                ))
              ) : progressStats ? (
                <>
                  <ProgressCard
                    title="Learning Progress"
                    value={learningProgressPercent}
                    subtitle={
                      totalTrackedDays
                        ? `${progressStats.total_problems_solved} problems solved in ${totalTrackedDays} days`
                        : `${progressStats.total_problems_solved} problems solved`
                    }
                    icon={<BookOpen className="w-6 h-6" />}
                  />
                  <ProgressCard
                    title="Quiz Accuracy"
                    value={quizAccuracyPercent}
                    subtitle={`Average score ${progressStats.avg_test_score.toFixed(1)}% across ${progressStats.total_tests_taken} tests`}
                    icon={<Target className="w-6 h-6" />}
                  />
                  <ProgressCard
                    title="Interview Readiness"
                    value={interviewReadinessPercent}
                    subtitle={
                      progressStats.total_interviews
                        ? `${progressStats.total_interviews} mock interviews completed`
                        : "Complete a mock interview to build momentum"
                    }
                    icon={<Brain className="w-6 h-6" />}
                  />
                </>
              ) : (
                <Card className="p-6 col-span-3 text-center text-muted-foreground">
                  No progress data available yet.
                </Card>
              )}
            </div>

            {/* Charts Section */}
            <div className="grid lg:grid-cols-2 gap-6">
              {/* Performance Trend */}
              <Card className="glass p-6">
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h2 className="text-xl font-semibold">Quiz Performance Trend</h2>
                    <TrendingUp className="w-5 h-5 text-accent" />
                  </div>
                  {metricsLoading ? (
                    <div className="h-[300px] rounded-lg bg-white/5 animate-pulse" />
                  ) : (
                    <p className="text-sm text-muted-foreground">No quiz activity recorded yet.</p>
                  )}
                </div>
              </Card>

              {/* Subject Performance */}
              <Card className="glass p-6">
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h2 className="text-xl font-semibold">Subject Mastery</h2>
                    <Brain className="w-5 h-5 text-accent" />
                  </div>
                  {metricsLoading ? (
                    <div className="h-[300px] rounded-lg bg-white/5 animate-pulse" />
                  ) : hasSkillData ? (
                    <ResponsiveContainer width="100%" height={300}>
                      <RadarChart data={skillRadarData}>
                        <PolarGrid stroke="rgba(255,255,255,0.1)" />
                        <PolarAngleAxis dataKey="skill" stroke="rgba(255,255,255,0.5)" />
                        <PolarRadiusAxis angle={90} domain={[0, 100]} stroke="rgba(255,255,255,0.5)" />
                        <Radar
                          name="Mastery %"
                          dataKey="value"
                          stroke="oklch(0.65 0.28 270)"
                          fill="oklch(0.65 0.28 270)"
                          fillOpacity={0.3}
                        />
                      </RadarChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-sm text-muted-foreground">Add more practice sessions to see skill insights.</p>
                  )}
                </div>
              </Card>
            </div>

            {/* Quick Actions */}
            <div className="grid md:grid-cols-3 gap-6">
              <Link href="/learning">
                <Card className="glass p-6 group hover:bg-white/15 transition-all cursor-pointer h-full">
                  <div className="flex items-center justify-between mb-4">
                    <BookOpen className="w-8 h-8 text-primary" />
                    <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-accent transition-colors" />
                  </div>
                  <h3 className="text-lg font-semibold mb-2">Personalized Learning</h3>
                  <p className="text-sm text-muted-foreground">Get AI-recommended courses tailored to your pace</p>
                </Card>
              </Link>

              <Link href="/quiz">
                <Card className="glass p-6 group hover:bg-white/15 transition-all cursor-pointer h-full">
                  <div className="flex items-center justify-between mb-4">
                    <Target className="w-8 h-8 text-accent" />
                    <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-accent transition-colors" />
                  </div>
                  <h3 className="text-lg font-semibold mb-2">Take a Quiz</h3>
                  <p className="text-sm text-muted-foreground">Test your knowledge with adaptive quizzes</p>
                </Card>
              </Link>

              <Link href="/interview">
                <Card className="glass p-6 group hover:bg-white/15 transition-all cursor-pointer h-full">
                  <div className="flex items-center justify-between mb-4">
                    <Brain className="w-8 h-8 text-secondary" />
                    <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-accent transition-colors" />
                  </div>
                  <h3 className="text-lg font-semibold mb-2">Interview Training</h3>
                  <p className="text-sm text-muted-foreground">Practice with AI interviewer and get feedback</p>
                </Card>
              </Link>
            </div>
          </div>
        </div>
      </main>
    </>
  )
}
