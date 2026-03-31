"use client"

import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { useState, useEffect, useMemo, useCallback, useRef } from "react"
import { learningAPI, type Recommendation, type TopicResource } from "@/lib/api"
import { 
  BookOpen, 
  Code, 
  TrendingUp, 
  AlertCircle, 
  CheckCircle,
  Clock,
  Filter,
  ExternalLink,
  Star,
  RefreshCw
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { toast } from "sonner"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/lib/store"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

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

// No video helpers needed

const completionDateFormatter = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
})

const topicTimestampFormatter = new Intl.DateTimeFormat('en-US', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
  timeZone: 'UTC',
})

const formatCompletionDate = (value?: string | null) => {
  if (!value) return null
  try {
    return completionDateFormatter.format(new Date(value))
  } catch {
    return null
  }
}

const truncateText = (value?: string | null, maxLength: number = 140) => {
  if (!value) return ""
  return value.length > maxLength ? `${value.slice(0, maxLength).trim()}...` : value
}

const formatTopicLabel = (value: string) => {
  if (!value || value === "all") return "All Topics"
  return value
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
}

const formatTopicTimestamp = (value?: string | null) => {
  if (!value) return null
  try {
    return topicTimestampFormatter.format(new Date(value))
  } catch {
    return null
  }
}

export default function RecommendationsPage() {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [topicFilter, setTopicFilter] = useState<string>("all")
  const [isHydrated, setIsHydrated] = useState(false)
  const [topicResources, setTopicResources] = useState<TopicResource[]>([])
  const [topicResourcesLoading, setTopicResourcesLoading] = useState(false)
  const [topicResourcesError, setTopicResourcesError] = useState<string | null>(null)
  const [topicResourcesTimestamp, setTopicResourcesTimestamp] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generationProgress, setGenerationProgress] = useState({ step: "", progress: 0 })
  const [wsConnected, setWsConnected] = useState(false)
  const [recentlyUpdated, setRecentlyUpdated] = useState<Set<number>>(new Set())
  const [wsRetryCount, setWsRetryCount] = useState(0)
  const router = useRouter()
  const { user, logout } = useAuthStore()
  const topicRequestRef = useRef<symbol | null>(null)

  const topicOptions = useMemo(() => {
    const presetTopics = [
      "DSA",
      "Data Analytics",
      "System Design",
      "Machine Learning",
      "AI",
      "DevOps",
      "Cloud Computing",
      "Interview Prep",
    ]
    const dynamicTopics = recommendations
      .map((rec) => rec.category)
      .filter((topic): topic is string => Boolean(topic && topic.trim().length > 0))

    const uniqueTopics = new Set<string>()
    ;[...presetTopics, ...dynamicTopics].forEach((topic) => {
      const normalized = topic.trim()
      if (normalized) {
        uniqueTopics.add(normalized)
      }
    })
    return Array.from(uniqueTopics).sort()
  }, [recommendations])

  const filteredRecommendations = useMemo(() => {
    const normalizedTopic = topicFilter.toLowerCase()
    return recommendations.filter((rec) => {
      if (topicFilter === "all") return true
      const matchesCategory = rec.category ? rec.category.toLowerCase().includes(normalizedTopic) : false
      const matchesTitle = rec.title ? rec.title.toLowerCase().includes(normalizedTopic) : false
      return matchesCategory || matchesTitle
    })
  }, [recommendations, topicFilter])

  const requestTopicResources = useCallback(async (selectedTopic: string) => {
    if (selectedTopic === "all") {
      topicRequestRef.current = null
      setTopicResources([])
      setTopicResourcesError(null)
      setTopicResourcesTimestamp(null)
      setTopicResourcesLoading(false)
      return
    }

    const token = Symbol(selectedTopic)
    topicRequestRef.current = token
    setTopicResourcesLoading(true)
    setTopicResourcesError(null)

    try {
      const response = await learningAPI.getTopicResources(selectedTopic)
      if (topicRequestRef.current !== token) {
        return
      }
      setTopicResources(response.items)
      setTopicResourcesTimestamp(response.fetched_at)
    } catch (err: any) {
      if (topicRequestRef.current !== token) {
        return
      }
      setTopicResources([])
      setTopicResourcesError(formatErrorMessage(err))
    } finally {
      if (topicRequestRef.current === token) {
        setTopicResourcesLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    setIsHydrated(true)
  }, [])

  useEffect(() => {
    if (!user) {
      router.replace("/login?next=/recommendations")
    }
  }, [user, router])

  // WebSocket connection
  useEffect(() => {
    if (typeof window === 'undefined' || !user?.id) {
      return
    }

    const connectWebSocket = () => {
      const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"
      const wsBase = apiBase.replace('http://', 'ws://').replace('https://', 'wss://')
      const wsUrl = `${wsBase}/ws/${encodeURIComponent(user.id)}`
      try {
        console.log('Attempting WebSocket connection to:', wsUrl)
        const ws = new WebSocket(wsUrl)

        ws.onopen = () => {
          console.log('WebSocket connected successfully')
          setWsConnected(true)
          setWsRetryCount(0)
        }

        ws.onmessage = (event) => {
          try {
            const parsed = JSON.parse(event.data)
            if (!parsed || typeof parsed !== 'object') {
              console.warn('WebSocket payload ignored (non-object):', parsed)
              return
            }

            const data = parsed as { type?: string; [key: string]: any }
            if (!data.type) {
              console.warn('WebSocket payload missing type field:', data)
              return
            }

            console.log('WebSocket message received:', data)
            
            switch (data.type) {
              case 'generation_progress':
                setGenerationProgress({
                  step: data.step,
                  progress: data.progress
                })
                break
                
              case 'generation_complete':
                setGenerating(false)
                setGenerationProgress({ step: "", progress: 0 })
                setRecommendations(data.recommendations)
                toast.success(`Generated ${data.recommendations.length} new recommendations!`)
                break
                
              case 'recommendation_updated':
                const updatedRec = data.recommendation
                setRecommendations(prev => 
                  prev.map(rec => 
                    rec.id === updatedRec.id ? updatedRec : rec
                  )
                )
                
                setRecentlyUpdated(prev => new Set([...(prev || new Set()), updatedRec.id]))
                setTimeout(() => {
                  setRecentlyUpdated(prev => {
                    const currentSet = prev || new Set()
                    const newSet = new Set(currentSet)
                    newSet.delete(updatedRec.id)
                    return newSet
                  })
                }, 3000)
                
                toast.info(`Recommendation "${updatedRec.title}" updated to ${updatedRec.status}`)
                break
            }
          } catch (err) {
            console.error('WebSocket message parse error:', err)
          }
        }
        
        ws.onclose = (event) => {
          console.log('WebSocket disconnected. Code:', event.code, 'Reason:', event.reason)
          setWsConnected(false)
          if (event.code !== 1000 && wsRetryCount < 5) {
            const retryDelay = Math.min(1000 * Math.pow(2, wsRetryCount), 30000)
            console.log(`Attempting to reconnect in ${retryDelay}ms (attempt ${wsRetryCount + 1}/5)`)
            setTimeout(() => {
              setWsRetryCount(prev => prev + 1)
              connectWebSocket()
            }, retryDelay)
          }
        }
        
        ws.onerror = (event) => {
          const diagnostic = {
            readyState: ws.readyState,
            url: wsUrl,
            timestamp: new Date().toISOString(),
          }
          console.warn('WebSocket issue detected. Switching to auto-refresh mode.', diagnostic)
          setWsConnected(false)
          
          if (wsRetryCount === 0) {
            toast.error('Real-time updates unavailable. Using auto-refresh mode instead.')
          }
        }
        
        return ws
      } catch (err) {
        console.error('WebSocket connection failed:', err)
        setWsConnected(false)
        return null
      }
    }

    setWsRetryCount(0)
    const ws = connectWebSocket()

    return () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close(1000, 'Component unmounting')
      }
    }
  }, [user?.id])

  useEffect(() => {
    if (!user) return
    fetchRecommendations()
  }, [user])

  useEffect(() => {
    if (!user) return
    requestTopicResources(topicFilter)
  }, [user, topicFilter, requestTopicResources])

  // Auto-refresh as fallback when WebSocket is not connected
  useEffect(() => {
    if (!user || wsConnected || loading) {
      return
    }

    const interval = setInterval(() => {
      fetchRecommendations()
    }, 30000)

    return () => clearInterval(interval)
  }, [wsConnected, loading, user])

  const fetchRecommendations = async () => {
    if (!user) return
    setLoading(true)
    setError(null)
    try {
      const data = await learningAPI.getRecommendations()
      setRecommendations(data)
    } catch (err: any) {
      if (err?.response?.status === 401) {
        setError("Your session has expired. Please sign in again.")
        logout()
        toast.error("Session expired. Please sign in again.")
        router.replace("/login?next=/recommendations")
        return
      }
      setError(formatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const generateNewRecommendations = async () => {
    if (!user) {
      toast.error("Please sign in to generate recommendations.")
      router.replace("/login?next=/recommendations")
      return
    }
    setGenerating(true)
    setError(null)
    setGenerationProgress({ step: "Starting AI analysis...", progress: 0 })
    
    try {
      await learningAPI.generateRecommendations()
      
      // If WebSocket is not connected, show fallback message and fetch recommendations after a delay
      if (!wsConnected) {
        toast.info('Generating recommendations... This may take a few moments.')
        // Simulate progress updates without WebSocket
        const progressSteps = [
          { step: "Analyzing your profile...", progress: 20 },
          { step: "Gathering learning data...", progress: 40 },
          { step: "Processing skill gaps...", progress: 60 },
          { step: "Generating recommendations...", progress: 80 },
          { step: "Finalizing suggestions...", progress: 100 }
        ]
        
        for (const step of progressSteps) {
          await new Promise(resolve => setTimeout(resolve, 1000))
          setGenerationProgress(step)
        }
        
        // Fetch the new recommendations
        await fetchRecommendations()
        setGenerating(false)
        setGenerationProgress({ step: "", progress: 0 })
        toast.success('AI recommendations generated successfully!')
      }
      // If WebSocket is connected, progress updates will come via WebSocket
    } catch (err: any) {
      setGenerating(false)
      setGenerationProgress({ step: "", progress: 0 })
      if (err?.response?.status === 401) {
        logout()
        toast.error("Session expired. Please sign in again.")
        router.replace("/login?next=/recommendations")
        return
      }
      setError(formatErrorMessage(err))
    }
  }

  const handleTopicContentRefresh = () => {
    if (topicFilter === "all") {
      toast.info("Choose a topic to load curated resources.")
      return
    }
    requestTopicResources(topicFilter)
  }

  const updateStatus = async (recId: number, newStatus: string) => {
    if (!user) {
      toast.error("Please sign in to update recommendations.")
      router.replace("/login?next=/recommendations")
      return
    }
    try {
      await learningAPI.updateRecommendationStatus(recId, newStatus)
      // The update will be reflected via WebSocket real-time update
      // No need to fetchRecommendations() here
    } catch (err: any) {
      if (err?.response?.status === 401) {
        logout()
        toast.error("Session expired. Please sign in again.")
        router.replace("/login?next=/recommendations")
        return
      }
      setError(formatErrorMessage(err))
    }
  }

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case "skill":
      case "technical":
        return <Code className="h-5 w-5" />
      case "course":
        return <BookOpen className="h-5 w-5" />
      case "practice":
        return <TrendingUp className="h-5 w-5" />
      default:
        return <Star className="h-5 w-5" />
    }
  }

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case "high":
        return "bg-red-100 text-red-800 border-red-200"
      case "medium":
        return "bg-yellow-100 text-yellow-800 border-yellow-200"
      case "low":
        return "bg-blue-100 text-blue-800 border-blue-200"
      default:
        return "bg-gray-100 text-gray-800 border-gray-200"
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "bg-green-100 text-green-800 border-green-200"
      case "in_progress":
        return "bg-blue-100 text-blue-800 border-blue-200"
      case "pending":
        return "bg-gray-100 text-gray-800 border-gray-200"
      case "dismissed":
        return "bg-gray-100 text-gray-500 border-gray-200"
      default:
        return "bg-gray-100 text-gray-800 border-gray-200"
    }
  }

  if (!isHydrated) {
    return (
      <div className="min-h-screen bg-background">
        <Navbar />
        <main className="container mx-auto px-4 py-8 pt-24">
          <Card className="glass p-6 text-center">
            <p className="text-muted-foreground">Loading recommendations...</p>
          </Card>
        </main>
      </div>
    )
  }

  if (!user) {
    return (
      <>
        <Navbar />
        <main className="min-h-screen flex items-center justify-center px-4">
          <Card className="glass w-full max-w-md p-8 text-center">
            <p className="text-muted-foreground">Redirecting to the login page...</p>
          </Card>
        </main>
      </>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <Navbar />
      
      <main className="container mx-auto px-4 py-8 pt-24">
        <div className="max-w-7xl mx-auto space-y-8">
          {/* Header */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-4xl font-bold gradient-text">AI Recommendations</h1>
                <p className="text-xl text-muted-foreground mt-2">
                  Personalized learning paths tailored to your goals
                </p>
                {wsConnected && (
                  <div className="flex items-center gap-2 mt-2">
                    <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                    <span className="text-sm text-green-600">Real-time updates enabled</span>
                  </div>
                )}
                {!wsConnected && (
                  <div className="flex items-center gap-2 mt-2">
                    <div className="w-2 h-2 bg-yellow-500 rounded-full animate-pulse"></div>
                    <span className="text-sm text-yellow-600">Auto-refresh mode (WebSocket unavailable)</span>
                  </div>
                )}
              </div>
              <Button
                onClick={generateNewRecommendations}
                disabled={generating}
                className="flex items-center gap-2"
              >
                <RefreshCw className={`h-4 w-4 ${generating ? 'animate-spin' : ''}`} />
                {generating ? 'Generating...' : 'Refresh'}
              </Button>
            </div>

            {/* Real-time Generation Progress */}
            {generating && (
              <Card className="glass p-6 bg-primary/10 border-primary">
                <div className="space-y-4">
                  <div className="flex items-center gap-2">
                    <RefreshCw className="h-5 w-5 animate-spin text-primary" />
                    <h3 className="font-semibold text-primary">Generating AI Recommendations</h3>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span>{generationProgress.step}</span>
                      <span>{generationProgress.progress}%</span>
                    </div>
                    <div className="w-full bg-secondary rounded-full h-2">
                      <div 
                        className="bg-primary h-2 rounded-full transition-all duration-500 ease-out"
                        style={{ width: `${generationProgress.progress}%` }}
                      ></div>
                    </div>
                  </div>
                </div>
              </Card>
            )}
          </div>

          {/* Error Message */}
          {error && (
            <Card className="glass p-4 bg-destructive/10 border-destructive">
              <div className="flex items-center gap-2 text-destructive">
                <AlertCircle className="h-5 w-5" />
                <p>{error}</p>
              </div>
            </Card>
          )}

          {/* Learning Resources */}
          <div className="space-y-6">
            {/* Filters */}
            <Card className="glass p-6">
              <div className="flex flex-wrap gap-4 items-center justify-between">
                <div className="flex items-center gap-2">
                  <Filter className="h-5 w-5 text-muted-foreground" />
                  <span className="font-medium">Choose a Topic</span>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted-foreground">Topic:</span>
                  <Select value={topicFilter} onValueChange={setTopicFilter}>
                    <SelectTrigger className="w-48 bg-background/80">
                      <SelectValue placeholder="Choose a topic" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Topics</SelectItem>
                      {topicOptions.map((topic) => (
                        <SelectItem key={topic} value={topic.toLowerCase()}>
                          {topic}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </Card>

            {topicFilter !== "all" && (
              <Card className="glass p-6 border border-primary/20 bg-primary/5">
                <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                  <div>
                    <h3 className="text-lg font-semibold">
                      Fresh picks for {formatTopicLabel(topicFilter)}
                    </h3>
                    <p className="text-sm text-muted-foreground">
                      Articles, tutorials, and practice problems sourced in real-time
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {topicResourcesTimestamp && (
                      <span className="text-xs text-muted-foreground">
                        Generated at {formatTopicTimestamp(topicResourcesTimestamp)} UTC
                      </span>
                    )}
                    <Button variant="outline" size="sm" onClick={handleTopicContentRefresh} disabled={topicResourcesLoading}>
                      <RefreshCw className={`h-4 w-4 mr-2 ${topicResourcesLoading ? "animate-spin" : ""}`} />
                      Refresh
                    </Button>
                  </div>
                </div>

                {topicResourcesLoading ? (
                  <div className="grid md:grid-cols-2 gap-4">
                    {[1, 2, 3, 4].map((item) => (
                      <Card key={item} className="glass p-4 animate-pulse">
                        <div className="h-4 bg-muted rounded w-3/4 mb-2"></div>
                        <div className="h-3 bg-muted rounded w-full mb-2"></div>
                        <div className="h-3 bg-muted rounded w-2/3"></div>
                      </Card>
                    ))}
                  </div>
                ) : topicResourcesError ? (
                  <Card className="glass p-4 bg-destructive/10 border-destructive">
                    <div className="flex items-center gap-2 text-destructive">
                      <AlertCircle className="h-4 w-4" />
                      <p>{topicResourcesError}</p>
                    </div>
                  </Card>
                ) : topicResources.length === 0 ? (
                  <Card className="glass p-6 text-center">
                    <p className="text-sm text-muted-foreground">
                      No live resources found right now. Try refreshing or choosing another topic.
                    </p>
                  </Card>
                ) : (
                  <div className="grid md:grid-cols-2 gap-4">
                    {topicResources.map((resource, index) => (
                      <Card key={`${resource.url}-${index}`} className="glass p-4 space-y-3">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="font-semibold leading-snug">{resource.title}</p>
                            <p className="text-xs text-muted-foreground mt-1">Source: {resource.source}</p>
                          </div>
                          <Badge variant="outline" className="uppercase text-[11px]">
                            {resource.content_type}
                          </Badge>
                        </div>
                        {resource.summary && (
                          <p className="text-sm text-muted-foreground">
                            {truncateText(resource.summary)}
                          </p>
                        )}
                        <div className="flex items-center justify-between">
                          <a
                            href={resource.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-primary hover:underline"
                          >
                            View resource
                          </a>
                          <ExternalLink className="h-4 w-4 text-primary" />
                        </div>
                      </Card>
                    ))}
                  </div>
                )}
              </Card>
            )}

              {/* Info Card */}
              {recommendations.length === 0 && !loading && (
                <Card className="glass p-6 bg-blue-50/10 border-blue-200/20">
                  <div className="flex items-start gap-3">
                    <Star className="h-6 w-6 text-blue-600 mt-1" />
                    <div>
                      <h3 className="text-lg font-semibold mb-2">
                        How AI Recommendations Work
                      </h3>
                      <p className="text-muted-foreground mb-3">
                        Our AI analyzes your activity to provide personalized learning recommendations:
                      </p>
                      <ul className="space-y-2 text-sm text-muted-foreground">
                        <li className="flex items-center gap-2">
                          <CheckCircle className="h-4 w-4 text-green-500" />
                          <span><strong>Resume Analysis:</strong> Identifies skill gaps and suggests improvements</span>
                        </li>
                        <li className="flex items-center gap-2">
                          <CheckCircle className="h-4 w-4 text-green-500" />
                          <span><strong>Test Performance:</strong> Recommends resources for weak topics</span>
                        </li>
                        <li className="flex items-center gap-2">
                          <CheckCircle className="h-4 w-4 text-green-500" />
                          <span><strong>Interview Feedback:</strong> Suggests areas to improve</span>
                        </li>
                      </ul>
                    </div>
                  </div>
                </Card>
              )}

              {/* Loading State */}
              {loading ? (
                <div className="grid md:grid-cols-2 gap-6">
                  {[1, 2, 3, 4].map((i) => (
                    <Card key={i} className="glass p-6 animate-pulse">
                      <div className="h-6 bg-muted rounded w-3/4 mb-4"></div>
                      <div className="h-4 bg-muted rounded w-full mb-2"></div>
                      <div className="h-4 bg-muted rounded w-2/3"></div>
                    </Card>
                  ))}
                </div>
              ) : recommendations.length === 0 ? (
                <Card className="glass p-12 text-center">
                  <BookOpen className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                  <h3 className="text-xl font-semibold mb-2">No Recommendations Yet</h3>
                  <p className="text-muted-foreground mb-4">
                    Complete some tests or upload your resume to get personalized recommendations!
                  </p>
                  <Button onClick={generateNewRecommendations} disabled={generating}>
                    <RefreshCw className={`h-4 w-4 mr-2 ${generating ? 'animate-spin' : ''}`} />
                    {generating ? 'Generating...' : 'Generate Recommendations'}
                  </Button>
                </Card>
              ) : filteredRecommendations.length === 0 ? (
                <Card className="glass p-12 text-center">
                  <Filter className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                  <h3 className="text-xl font-semibold mb-2">No matches for this topic</h3>
                  <p className="text-muted-foreground mb-4">
                    Try selecting a different topic or clear the filters to see all recommendations.
                  </p>
                  <div className="flex gap-2 justify-center">
                    <Button variant="outline" onClick={() => setTopicFilter("all")}>
                      Clear Topic Filter
                    </Button>
                  </div>
                </Card>
              ) : (
                <div className="grid md:grid-cols-2 gap-6">
                  {filteredRecommendations.map((rec) => {
                    const formattedCompletionDate = formatCompletionDate(rec.completed_at)

                    return (
                      <Card 
                        key={rec.id} 
                        className={`glass p-6 space-y-4 hover:shadow-lg transition-all duration-500 ${
                          recentlyUpdated.has(rec.id) 
                            ? 'ring-2 ring-primary/50 bg-primary/5 animate-pulse' 
                            : ''
                        }`}
                      >
                      {/* Header */}
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex items-start gap-3">
                          <div className="p-2 bg-primary/10 rounded-lg">
                            {getCategoryIcon(rec.category)}
                          </div>
                          <div className="flex-1">
                            <h3 className="text-lg font-semibold">{rec.title}</h3>
                            <p className="text-sm text-muted-foreground mt-1">
                              {rec.description}
                            </p>
                          </div>
                        </div>
                      </div>

                      {/* Badges */}
                      <div className="flex flex-wrap gap-2">
                        <Badge className={getPriorityColor(rec.priority)}>
                          {rec.priority.toUpperCase()} Priority
                        </Badge>
                        <Badge className={getStatusColor(rec.status)}>
                          {rec.status.replace("_", " ").toUpperCase()}
                        </Badge>
                        <Badge variant="outline" className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {rec.estimated_time}
                        </Badge>
                      </div>

                      {/* Resources */}
                      {rec.resources && rec.resources.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-sm font-medium">Resources:</p>
                          <div className="space-y-1">
                            {rec.resources.map((resource, idx) => (
                              <a
                                key={idx}
                                href={resource.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-2 text-sm text-primary hover:underline"
                              >
                                <ExternalLink className="h-3 w-3" />
                                {resource.title}
                              </a>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Source */}
                      <p className="text-xs text-muted-foreground">
                        Based on: {rec.source.replace("_", " ")}
                      </p>

                      {/* Actions */}
                      <div className="flex gap-2 pt-2">
                        {rec.status === "pending" && (
                          <Button
                            size="sm"
                            onClick={() => updateStatus(rec.id, "in_progress")}
                            className="flex-1"
                          >
                            Start Learning
                          </Button>
                        )}
                        {rec.status === "in_progress" && (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => updateStatus(rec.id, "completed")}
                              className="flex-1"
                            >
                              <CheckCircle className="h-4 w-4 mr-1" />
                              Mark Complete
                            </Button>
                          </>
                        )}
                        {rec.status === "completed" && (
                          <div className="flex-1 text-center py-2 text-sm text-green-600 font-medium">
                            {formattedCompletionDate ? `✓ Completed on ${formattedCompletionDate}` : '✓ Completed'}
                          </div>
                        )}
                        {rec.status !== "dismissed" && rec.status !== "completed" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => updateStatus(rec.id, "dismissed")}
                          >
                            Dismiss
                          </Button>
                        )}
                      </div>
                      </Card>
                    )
                  })}
                </div>
              )}
            </div>
        </div>
      </main>
    </div>
  )
}
