"use client"

// page relies on client-side React state

// reusable components from design system
import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

// iconography used for feedback and status
import { Clock, BarChart3, Brain, CheckCircle2, XCircle, Trophy, ArrowLeft, Loader2 } from "lucide-react"

// hooks for state and side effects
import { useState, useEffect } from "react"

// auth store and navigation helpers
import { useAuthStore } from "@/lib/store"
import { useRouter } from "next/navigation"

// backend API base, set via NEXT_PUBLIC_API_BASE or fallback to localhost
const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "")
const TOKEN_STORAGE_KEYS = ["auth_token", "token", "access_token"] as const

const getStoredAccessToken = () => {
  for (const key of TOKEN_STORAGE_KEYS) {
    const value = localStorage.getItem(key)
    if (value) {
      return value
    }
  }
  return null
}

const persistAccessToken = (token: string) => {
  TOKEN_STORAGE_KEYS.forEach((key) => localStorage.setItem(key, token))
}

let refreshPromise: Promise<string | null> | null = null

const refreshAccessToken = async (): Promise<string | null> => {
  const refreshToken = localStorage.getItem("refresh_token")
  if (!refreshToken) return null

  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })

        if (!response.ok) {
          return null
        }

        const data = await response.json()
        if (data.access_token) {
          persistAccessToken(data.access_token)
        }
        if (data.refresh_token) {
          localStorage.setItem("refresh_token", data.refresh_token)
        }
        return data.access_token ?? null
      } catch (error) {
        console.error("Token refresh failed:", error)
        return null
      } finally {
        refreshPromise = null
      }
    })()
  }

  return refreshPromise
}

const authFetch = async (url: string, init: RequestInit = {}) => {
  const firstHeaders = new Headers(init.headers || {})
  const token = getStoredAccessToken()
  if (token) {
    firstHeaders.set("Authorization", `Bearer ${token}`)
  }

  const firstResponse = await fetch(url, { ...init, headers: firstHeaders })
  if (firstResponse.status !== 401) {
    return firstResponse
  }

  const refreshedToken = await refreshAccessToken()
  if (!refreshedToken) {
    return firstResponse
  }

  const retryHeaders = new Headers(init.headers || {})
  retryHeaders.set("Authorization", `Bearer ${refreshedToken}`)

  return fetch(url, { ...init, headers: retryHeaders })
}

// quiz metadata returned from server
interface Quiz {
  id: number
  title: string
  description: string
  subject: string
  difficulty_level: string
  total_questions: number
  time_limit_minutes: number
  quiz_type: string
  content_source?: string
  created_at: string
}

// detailed structure of each quiz question (MCQ, etc.)
interface Question {
  id: number
  quiz_id: number
  question_text: string
  question_type: string
  options: string[] | null
  points: number
  topic_tags: string[] | null
  question_order: number
}

// response shape when a completed quiz attempt is returned
interface QuizResult {
  attempt_id: number
  quiz_title: string
  total_questions: number
  questions_attempted: number
  correct_answers: number
  wrong_answers: number
  skipped_questions: number
  total_score: number
  max_score: number
  percentage: number
  passed: boolean
  time_taken_minutes: number
  ai_feedback: string | null
  strengths: string[] | null
  weaknesses: string[] | null
  recommended_topics: string[] | null
}

interface ScrapeSource {
  id: string
  name: string
  domain: string
  seed_url: string
}

export default function TakeTestsPage() {
  const router = useRouter()
  const { user } = useAuthStore()
  const [loading, setLoading] = useState(false)
  const [quizzes, setQuizzes] = useState<Quiz[]>([])
  const [showGenerator, setShowGenerator] = useState(false)
  const [currentQuiz, setCurrentQuiz] = useState<Quiz | null>(null)
  const [questions, setQuestions] = useState<Question[]>([])
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)
  const [answers, setAnswers] = useState<{ [key: number]: string[] }>({})
  const [attemptId, setAttemptId] = useState<number | null>(null)
  const [quizResult, setQuizResult] = useState<QuizResult | null>(null)
  const [timeLeft, setTimeLeft] = useState(0)
  const [quizStartTime, setQuizStartTime] = useState<Date | null>(null)

  // Quiz generation form
  const [subject, setSubject] = useState("")
  const [topic, setTopic] = useState("")
  const [difficulty, setDifficulty] = useState("medium")
  const [numQuestions, setNumQuestions] = useState(10)
  const [sourceMode, setSourceMode] = useState("auto")
  const [scrapeSourceId, setScrapeSourceId] = useState("all")
  const [scrapeSources, setScrapeSources] = useState<ScrapeSource[]>([])

  useEffect(() => {
    if (!user) {
      router.push("/login")
      return
    }
    fetchQuizzes()
    fetchScrapeSources()
  }, [user])

  // Timer
  useEffect(() => {
    if (currentQuiz && attemptId && timeLeft > 0) {
      const timer = setInterval(() => {
        setTimeLeft((prev) => {
          if (prev <= 1) {
            handleSubmitQuiz()
            return 0
          }
          return prev - 1
        })
      }, 1000)
      return () => clearInterval(timer)
    }
  }, [currentQuiz, attemptId, timeLeft])

  const getAuthHeader = (): Record<string, string> => {
    const token = getStoredAccessToken()
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  const fetchQuizzes = async () => {
    try {
      const response = await authFetch(`${API_BASE_URL}/quiz/list?limit=50`, {
        headers: getAuthHeader(),
      })
      if (response.ok) {
        const data = await response.json()
        setQuizzes(data)
      }
    } catch (error) {
      console.error("Error fetching quizzes:", error)
    }
  }

  const fetchScrapeSources = async () => {
    try {
      const response = await authFetch(`${API_BASE_URL}/quiz/scrape-sources`, {
        headers: getAuthHeader(),
      })
      if (response.ok) {
        const data = await response.json()
        if (Array.isArray(data)) {
          setScrapeSources(data)
        }
      }
    } catch (error) {
      console.error("Error fetching quiz scrape sources:", error)
    }
  }

  const handleGenerateQuiz = async () => {
    if (!subject) {
      alert("Please enter a subject")
      return
    }

    setLoading(true)
    try {
      const response = await authFetch(`${API_BASE_URL}/quiz/generate`, {
        method: "POST",
        headers: {
          ...getAuthHeader(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          subject,
          topic: topic || null,
          difficulty,
          num_questions: numQuestions,
          quiz_type: "mixed",
          source_mode: sourceMode,
          scrape_source_ids: scrapeSourceId === "all" ? null : [scrapeSourceId],
        }),
      })

      if (response.ok) {
        const quiz = await response.json()
        setShowGenerator(false)
        await fetchQuizzes()
        alert(`Quiz "${quiz.title}" generated successfully!`)
        setSubject("")
        setTopic("")
        setDifficulty("medium")
        setNumQuestions(10)
        setSourceMode("auto")
        setScrapeSourceId("all")
      } else {
        const error = await response.json()
        alert(`Failed to generate quiz: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error generating quiz:", error)
      alert("Failed to generate quiz. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  const handleStartQuiz = async (quiz: Quiz) => {
    setLoading(true)
    try {
      const quizResponse = await authFetch(`${API_BASE_URL}/quiz/${quiz.id}`, {
        headers: getAuthHeader(),
      })
      const quizData = await quizResponse.json()

      const attemptResponse = await authFetch(`${API_BASE_URL}/quiz/attempt/start`, {
        method: "POST",
        headers: {
          ...getAuthHeader(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ quiz_id: quiz.id }),
      })

      if (attemptResponse.ok) {
        const attempt = await attemptResponse.json()
        setCurrentQuiz(quiz)
        setQuestions(quizData.questions)
        setAttemptId(attempt.id)
        setCurrentQuestionIndex(0)
        setAnswers({})
        setTimeLeft(quiz.time_limit_minutes * 60)
        setQuizStartTime(new Date())
      }
    } catch (error) {
      console.error("Error starting quiz:", error)
      alert("Failed to start quiz")
    } finally {
      setLoading(false)
    }
  }

  const handleAnswerSelect = (questionId: number, answer: string) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: [answer],
    }))
  }

  const handleNext = () => {
    if (currentQuestionIndex < questions.length - 1) {
      setCurrentQuestionIndex((prev) => prev + 1)
    }
  }

  const handlePrevious = () => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex((prev) => prev - 1)
    }
  }

  const handleSubmitQuiz = async () => {
    if (!attemptId || !quizStartTime) return

    setLoading(true)
    try {
      const submissionAnswers = Object.entries(answers).map(([questionId, userAnswer]) => ({
        question_id: parseInt(questionId),
        user_answer: userAnswer,
        time_taken_seconds: (new Date().getTime() - quizStartTime.getTime()) / 1000,
      }))

      const response = await authFetch(`${API_BASE_URL}/quiz/attempt/submit`, {
        method: "POST",
        headers: {
          ...getAuthHeader(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          attempt_id: attemptId,
          answers: submissionAnswers,
        }),
      })

      if (response.ok) {
        const result = await response.json()
        setQuizResult(result)
        setCurrentQuiz(null)
        setAttemptId(null)
      }
    } catch (error) {
      console.error("Error submitting quiz:", error)
      alert("Failed to submit quiz")
    } finally {
      setLoading(false)
    }
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, "0")}`
  }

  // Quiz Result View
  if (quizResult) {
    return (
      <>
        <Navbar />
        <main className="pt-20 pb-12">
          <div className="max-w-4xl mx-auto px-4">
            <Card className="glass p-8">
              <div className="space-y-6">
                <div className="text-center">
                  <Trophy className={`w-16 h-16 mx-auto mb-4 ${quizResult.passed ? "text-green-500" : "text-yellow-500"}`} />
                  <h2 className="text-3xl font-bold mb-2">{quizResult.quiz_title}</h2>
                  <p className="text-4xl font-bold gradient-text">{quizResult.percentage.toFixed(1)}%</p>
                  <p className="text-muted-foreground mt-2">
                    {quizResult.passed ? "✅ Passed!" : "Keep practicing!"}
                  </p>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="text-center p-4 bg-green-500/10 rounded-lg">
                    <CheckCircle2 className="w-8 h-8 text-green-500 mx-auto mb-2" />
                    <p className="text-2xl font-bold">{quizResult.correct_answers}</p>
                    <p className="text-sm text-muted-foreground">Correct</p>
                  </div>
                  <div className="text-center p-4 bg-red-500/10 rounded-lg">
                    <XCircle className="w-8 h-8 text-red-500 mx-auto mb-2" />
                    <p className="text-2xl font-bold">{quizResult.wrong_answers}</p>
                    <p className="text-sm text-muted-foreground">Wrong</p>
                  </div>
                  <div className="text-center p-4 bg-yellow-500/10 rounded-lg">
                    <Clock className="w-8 h-8 text-yellow-500 mx-auto mb-2" />
                    <p className="text-2xl font-bold">{quizResult.time_taken_minutes.toFixed(1)}</p>
                    <p className="text-sm text-muted-foreground">Minutes</p>
                  </div>
                  <div className="text-center p-4 bg-blue-500/10 rounded-lg">
                    <BarChart3 className="w-8 h-8 text-blue-500 mx-auto mb-2" />
                    <p className="text-2xl font-bold">{quizResult.total_score}/{quizResult.max_score}</p>
                    <p className="text-sm text-muted-foreground">Score</p>
                  </div>
                </div>

                {quizResult.ai_feedback && (
                  <div className="p-4 bg-primary/10 rounded-lg">
                    <h3 className="font-semibold mb-2">AI Feedback</h3>
                    <p className="text-sm">{quizResult.ai_feedback}</p>
                  </div>
                )}

                {quizResult.strengths && quizResult.strengths.length > 0 && (
                  <div>
                    <h3 className="font-semibold mb-2 text-green-500">✓ Strengths</h3>
                    <ul className="list-disc list-inside space-y-1">
                      {quizResult.strengths.map((s, i) => (
                        <li key={i} className="text-sm">{s}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {quizResult.weaknesses && quizResult.weaknesses.length > 0 && (
                  <div>
                    <h3 className="font-semibold mb-2 text-yellow-500">⚠ Areas to Improve</h3>
                    <ul className="list-disc list-inside space-y-1">
                      {quizResult.weaknesses.map((w, i) => (
                        <li key={i} className="text-sm">{w}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {quizResult.recommended_topics && quizResult.recommended_topics.length > 0 && (
                  <div>
                    <h3 className="font-semibold mb-2">📚 Recommended Topics</h3>
                    <div className="flex flex-wrap gap-2">
                      {quizResult.recommended_topics.map((topic, i) => (
                        <span key={i} className="px-3 py-1 bg-accent/20 rounded-full text-sm">
                          {topic}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex gap-4">
                  <Button onClick={() => setQuizResult(null)} className="flex-1">
                    <ArrowLeft className="w-4 h-4 mr-2" />
                    Back to Quizzes
                  </Button>
                  <Button onClick={fetchQuizzes} variant="outline" className="flex-1">
                    Try Another Quiz
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </main>
      </>
    )
  }

  // Quiz Taking View
  if (currentQuiz && questions.length > 0 && attemptId) {
    const currentQuestion = questions[currentQuestionIndex]
    const answered = currentQuestion.id in answers

    return (
      <>
        <Navbar />
        <main className="pt-20 pb-12">
          <div className="max-w-4xl mx-auto px-4">
            <Card className="glass p-6 mb-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold">{currentQuiz.title}</h2>
                  <p className="text-sm text-muted-foreground">
                    Question {currentQuestionIndex + 1} of {questions.length}
                  </p>
                </div>
                <div className="text-center">
                  <Clock className="w-6 h-6 mx-auto mb-1 text-accent" />
                  <p className="text-2xl font-bold font-mono">{formatTime(timeLeft)}</p>
                </div>
              </div>
              <div className="mt-4 w-full bg-muted rounded-full h-2">
                <div
                  className="bg-accent h-2 rounded-full transition-all"
                  style={{ width: `${((currentQuestionIndex + 1) / questions.length) * 100}%` }}
                />
              </div>
            </Card>

            <Card className="glass p-8">
              <div className="space-y-6">
                <div>
                  <p className="text-lg mb-4">{currentQuestion.question_text}</p>
                  {currentQuestion.topic_tags && currentQuestion.topic_tags.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-4">
                      {currentQuestion.topic_tags.map((tag, i) => (
                        <span key={i} className="px-2 py-1 bg-primary/20 rounded text-xs">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {currentQuestion.question_type === "mcq" && currentQuestion.options && (
                  <div className="space-y-3">
                    {currentQuestion.options.map((option, index) => (
                      <button
                        key={index}
                        onClick={() => handleAnswerSelect(currentQuestion.id, option)}
                        className={`w-full p-4 text-left rounded-lg border-2 transition-all ${
                          answers[currentQuestion.id]?.[0] === option
                            ? "border-accent bg-accent/20"
                            : "border-border hover:border-accent/50"
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                            answers[currentQuestion.id]?.[0] === option
                              ? "border-accent bg-accent"
                              : "border-muted-foreground"
                          }`}>
                            {answers[currentQuestion.id]?.[0] === option && (
                              <div className="w-2 h-2 bg-white rounded-full" />
                            )}
                          </div>
                          <span>{option}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {currentQuestion.question_type === "true_false" && currentQuestion.options && (
                  <div className="flex gap-4">
                    {currentQuestion.options.map((option, index) => (
                      <button
                        key={index}
                        onClick={() => handleAnswerSelect(currentQuestion.id, option)}
                        className={`flex-1 p-6 text-center rounded-lg border-2 transition-all ${
                          answers[currentQuestion.id]?.[0] === option
                            ? "border-accent bg-accent/20"
                            : "border-border hover:border-accent/50"
                        }`}
                      >
                        <p className="text-xl font-semibold">{option}</p>
                      </button>
                    ))}
                  </div>
                )}

                <div className="flex gap-4 pt-4">
                  <Button
                    onClick={handlePrevious}
                    disabled={currentQuestionIndex === 0}
                    variant="outline"
                  >
                    Previous
                  </Button>
                  
                  {currentQuestionIndex < questions.length - 1 ? (
                    <Button onClick={handleNext} className="flex-1" disabled={!answered}>
                      Next
                    </Button>
                  ) : (
                    <Button onClick={handleSubmitQuiz} className="flex-1 bg-green-600 hover:bg-green-700" disabled={loading}>
                      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Submit Quiz"}
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          </div>
        </main>
      </>
    )
  }

  // Quiz Generator View
  if (showGenerator) {
    return (
      <>
        <Navbar />
        <main className="pt-20 pb-12">
          <div className="max-w-2xl mx-auto px-4">
            <Card className="glass p-8">
              <h2 className="text-2xl font-bold mb-6 gradient-text">Generate AI Quiz</h2>
              <p className="text-sm text-muted-foreground mb-4">
                Tests are generated using web resources from Google Interview Warmup, Exponent, and Tech Interview Handbook when available.
              </p>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="subject">Subject *</Label>
                  <Input
                    id="subject"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder="e.g., Data Structures, Algorithms, Python"
                  />
                </div>
                <div>
                  <Label htmlFor="topic">Topic (Optional)</Label>
                  <Input
                    id="topic"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder="e.g., Arrays, Sorting, Loops"
                  />
                </div>
                <div>
                  <Label htmlFor="difficulty">Difficulty</Label>
                  <Select value={difficulty} onValueChange={setDifficulty}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="easy">Easy</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="hard">Hard</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label htmlFor="numQuestions">Number of Questions</Label>
                  <Select value={numQuestions.toString()} onValueChange={(v) => setNumQuestions(parseInt(v))}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="5">5 Questions</SelectItem>
                      <SelectItem value="10">10 Questions</SelectItem>
                      <SelectItem value="15">15 Questions</SelectItem>
                      <SelectItem value="20">20 Questions</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label htmlFor="sourceMode">Question Source</Label>
                  <Select value={sourceMode} onValueChange={setSourceMode}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Auto (Web + Internal fallback)</SelectItem>
                      <SelectItem value="web_only">Web scraped only</SelectItem>
                      <SelectItem value="internal_only">Internal bank only</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {sourceMode !== "internal_only" && (
                  <div>
                    <Label htmlFor="scrapeSource">Web Source</Label>
                    <Select value={scrapeSourceId} onValueChange={setScrapeSourceId}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All web sources</SelectItem>
                        {scrapeSources.map((source) => (
                          <SelectItem key={source.id} value={source.id}>
                            {source.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <div className="flex gap-4 pt-4">
                  <Button onClick={() => setShowGenerator(false)} variant="outline" className="flex-1">
                    Cancel
                  </Button>
                  <Button onClick={handleGenerateQuiz} disabled={loading} className="flex-1">
                    {loading ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Generating...
                      </>
                    ) : (
                      <>
                        <Brain className="w-4 h-4 mr-2" />
                        Generate Quiz
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </main>
      </>
    )
  }

  // Quiz List View
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
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-4xl font-bold gradient-text">AI-Powered Quizzes</h1>
                <p className="text-muted-foreground mt-2">
                  Take Tests with AI-generated and web-scraped interview questions
                </p>
              </div>
              <Button onClick={() => setShowGenerator(true)}>
                <Brain className="w-4 h-4 mr-2" />
                Generate Quiz
              </Button>
            </div>

            {quizzes.length === 0 ? (
              <Card className="glass p-12 text-center">
                <Brain className="w-16 h-16 text-muted-foreground mx-auto mb-4" />
                <h3 className="text-xl font-semibold mb-2">No Quizzes Yet</h3>
                <p className="text-muted-foreground mb-6">
                  Generate your first AI-powered quiz to get started
                </p>
                <Button onClick={() => setShowGenerator(true)}>
                  <Brain className="w-4 h-4 mr-2" />
                  Generate Your First Quiz
                </Button>
              </Card>
            ) : (
              <div className="grid md:grid-cols-2 gap-6">
                {quizzes.map((quiz) => (
                  <Card key={quiz.id} className="glass p-6 hover:bg-white/15 transition-all">
                    <div className="space-y-4">
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <h3 className="text-lg font-semibold">{quiz.title}</h3>
                          <span
                            className={`text-xs font-semibold px-2 py-1 rounded-full ${
                              quiz.difficulty_level === "hard"
                                ? "bg-red-500/20 text-red-300"
                                : quiz.difficulty_level === "medium"
                                  ? "bg-yellow-500/20 text-yellow-300"
                                  : "bg-green-500/20 text-green-300"
                            }`}
                          >
                            {quiz.difficulty_level}
                          </span>
                        </div>
                        <p className="text-sm text-muted-foreground">{quiz.description || quiz.subject}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Source: {quiz.content_source === "web_scraped" ? "Web scraped" : "Internal"}
                        </p>
                      </div>

                      <div className="flex items-center gap-4 text-sm">
                        <div className="flex items-center gap-2">
                          <BarChart3 className="w-4 h-4 text-muted-foreground" />
                          <span>{quiz.total_questions} Questions</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Clock className="w-4 h-4 text-muted-foreground" />
                          <span>{quiz.time_limit_minutes} min</span>
                        </div>
                      </div>

                      <Button
                        onClick={() => handleStartQuiz(quiz)}
                        className="w-full"
                        disabled={loading}
                      >
                        {loading ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          "Start Quiz"
                        )}
                      </Button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  )
}
