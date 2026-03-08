"use client"

import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { useState, useEffect } from "react"
import { learningAPI, type Recommendation } from "@/lib/api"
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
  RefreshCw,
  Youtube,
  Play,
  Eye,
  ThumbsUp
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface YouTubeVideo {
  id: string
  title: string
  thumbnail: string
  channel: string
  views: string
  publishedAt: string
  duration: string
  url: string
}

interface TopicRecommendations {
  topic: string
  videos: YouTubeVideo[]
  priority: string
  category: string
}

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

// Mock YouTube video fetcher (simulates API call)
const fetchYouTubeVideosForTopic = async (topic: string, category: string): Promise<YouTubeVideo[]> => {
  // In production, you would call YouTube Data API v3
  // For now, we'll return mock data that looks realistic
  const mockVideos: YouTubeVideo[] = [
    {
      id: `${topic}-1`,
      title: `Complete ${topic} Tutorial for Beginners 2025`,
      thumbnail: `https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg`,
      channel: "Tech Mastery",
      views: "1.2M",
      publishedAt: "2 days ago",
      duration: "45:30",
      url: `https://youtube.com/results?search_query=${encodeURIComponent(topic + ' tutorial')}`
    },
    {
      id: `${topic}-2`,
      title: `${topic} - Advanced Concepts Explained`,
      thumbnail: `https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg`,
      channel: "Code Academy Pro",
      views: "856K",
      publishedAt: "1 week ago",
      duration: "1:12:45",
      url: `https://youtube.com/results?search_query=${encodeURIComponent(topic + ' advanced')}`
    },
    {
      id: `${topic}-3`,
      title: `Learn ${topic} in 2025 - Complete Course`,
      thumbnail: `https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg`,
      channel: "Programming Hub",
      views: "2.4M",
      publishedAt: "3 weeks ago",
      duration: "3:24:15",
      url: `https://youtube.com/results?search_query=${encodeURIComponent(topic + ' course 2025')}`
    },
    {
      id: `${topic}-4`,
      title: `${topic} Project Tutorial - Build Real Apps`,
      thumbnail: `https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg`,
      channel: "Dev Projects",
      views: "543K",
      publishedAt: "5 days ago",
      duration: "2:15:30",
      url: `https://youtube.com/results?search_query=${encodeURIComponent(topic + ' project tutorial')}`
    },
    {
      id: `${topic}-5`,
      title: `${topic} Interview Questions and Answers`,
      thumbnail: `https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg`,
      channel: "Interview Prep",
      views: "678K",
      publishedAt: "1 month ago",
      duration: "52:18",
      url: `https://youtube.com/results?search_query=${encodeURIComponent(topic + ' interview questions')}`
    },
    {
      id: `${topic}-6`,
      title: `${topic} Best Practices and Tips`,
      thumbnail: `https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg`,
      channel: "Tech Tips Daily",
      views: "345K",
      publishedAt: "2 weeks ago",
      duration: "38:42",
      url: `https://youtube.com/results?search_query=${encodeURIComponent(topic + ' best practices')}`
    }
  ]
  
  return mockVideos
}

// Extract topics from recommendations
const extractTopicsFromRecommendations = (recommendations: Recommendation[]): string[] => {
  const topics = new Set<string>()
  
  recommendations.forEach(rec => {
    // Extract topic from title or description
    if (rec.title) topics.add(rec.title)
    if (rec.category) topics.add(rec.category)
    // You can add more intelligent topic extraction here
  })
  
  return Array.from(topics)
}

export default function RecommendationsPage() {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterStatus, setFilterStatus] = useState<string>("all")
  const [filterPriority, setFilterPriority] = useState<string>("all")
  const [generating, setGenerating] = useState(false)
  const [activeTab, setActiveTab] = useState<string>("videos")
  const [topicRecommendations, setTopicRecommendations] = useState<TopicRecommendations[]>([])
  const [loadingVideos, setLoadingVideos] = useState(false)
  const [selectedTopic, setSelectedTopic] = useState<string>("all")

  useEffect(() => {
    fetchRecommendations()
  }, [filterStatus, filterPriority])

  useEffect(() => {
    if (recommendations.length > 0 && activeTab === "videos") {
      loadVideoRecommendations()
    }
  }, [recommendations, activeTab])

  const loadVideoRecommendations = async () => {
    setLoadingVideos(true)
    try {
      const topicRecs: TopicRecommendations[] = []
      
      // Group recommendations by topic/title
      const uniqueTopics = Array.from(new Set(recommendations.map(r => r.title)))
      
      for (const topic of uniqueTopics.slice(0, 10)) { // Limit to 10 topics
        const relatedRec = recommendations.find(r => r.title === topic)
        if (relatedRec) {
          const videos = await fetchYouTubeVideosForTopic(topic, relatedRec.category)
          topicRecs.push({
            topic,
            videos,
            priority: relatedRec.priority,
            category: relatedRec.category
          })
        }
      }
      
      setTopicRecommendations(topicRecs)
    } catch (err) {
      console.error("Error loading videos:", err)
    } finally {
      setLoadingVideos(false)
    }
  }

  const fetchRecommendations = async () => {
    setLoading(true)
    setError(null)
    try {
      const status = filterStatus === "all" ? undefined : filterStatus
      const priority = filterPriority === "all" ? undefined : filterPriority
      const data = await learningAPI.getRecommendations(status, priority)
      setRecommendations(data)
    } catch (err: any) {
      setError(formatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const generateNewRecommendations = async () => {
    setGenerating(true)
    setError(null)
    try {
      await learningAPI.generateRecommendations()
      await fetchRecommendations()
    } catch (err: any) {
      setError(formatErrorMessage(err))
    } finally {
      setGenerating(false)
    }
  }

  const updateStatus = async (recId: number, newStatus: string) => {
    try {
      await learningAPI.updateRecommendationStatus(recId, newStatus)
      fetchRecommendations()
    } catch (err: any) {
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
                  Personalized learning paths and video tutorials based on your goals
                </p>
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

          {/* Tabs */}
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList className="grid w-full max-w-md grid-cols-2">
              <TabsTrigger value="videos" className="flex items-center gap-2">
                <Youtube className="h-4 w-4" />
                Video Tutorials
              </TabsTrigger>
              <TabsTrigger value="resources" className="flex items-center gap-2">
                <BookOpen className="h-4 w-4" />
                Learning Resources
              </TabsTrigger>
            </TabsList>

            {/* Video Tutorials Tab */}
            <TabsContent value="videos" className="space-y-6">
              {/* Topic Filter */}
              {topicRecommendations.length > 0 && (
                <Card className="glass p-6">
                  <div className="flex flex-wrap gap-4 items-center">
                    <div className="flex items-center gap-2">
                      <Filter className="h-5 w-5 text-muted-foreground" />
                      <span className="font-medium">Topics:</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant={selectedTopic === "all" ? "default" : "outline"}
                        size="sm"
                        onClick={() => setSelectedTopic("all")}
                      >
                        All Topics
                      </Button>
                      {topicRecommendations.map((topicRec) => (
                        <Button
                          key={topicRec.topic}
                          variant={selectedTopic === topicRec.topic ? "default" : "outline"}
                          size="sm"
                          onClick={() => setSelectedTopic(topicRec.topic)}
                        >
                          {topicRec.topic}
                        </Button>
                      ))}
                    </div>
                  </div>
                </Card>
              )}

              {/* Loading State */}
              {loadingVideos ? (
                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {[1, 2, 3, 4, 5, 6].map((i) => (
                    <Card key={i} className="glass p-4 animate-pulse">
                      <div className="aspect-video bg-muted rounded mb-3"></div>
                      <div className="h-4 bg-muted rounded w-3/4 mb-2"></div>
                      <div className="h-3 bg-muted rounded w-1/2"></div>
                    </Card>
                  ))}
                </div>
              ) : topicRecommendations.length === 0 ? (
                <Card className="glass p-12 text-center">
                  <Youtube className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                  <h3 className="text-xl font-semibold mb-2">No Video Recommendations Yet</h3>
                  <p className="text-muted-foreground mb-4">
                    Generate recommendations first to get personalized video tutorials!
                  </p>
                  <Button onClick={generateNewRecommendations} disabled={generating}>
                    <RefreshCw className={`h-4 w-4 mr-2 ${generating ? 'animate-spin' : ''}`} />
                    {generating ? 'Generating...' : 'Generate Recommendations'}
                  </Button>
                </Card>
              ) : (
                <div className="space-y-8">
                  {topicRecommendations
                    .filter(topicRec => selectedTopic === "all" || topicRec.topic === selectedTopic)
                    .map((topicRec) => (
                      <div key={topicRec.topic} className="space-y-4">
                        {/* Topic Header */}
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <h2 className="text-2xl font-bold">{topicRec.topic}</h2>
                            <Badge className={getPriorityColor(topicRec.priority)}>
                              {topicRec.priority.toUpperCase()}
                            </Badge>
                          </div>
                          <a
                            href={`https://youtube.com/results?search_query=${encodeURIComponent(topicRec.topic + ' tutorial')}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-primary hover:underline flex items-center gap-1"
                          >
                            View More on YouTube
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        </div>

                        {/* Video Grid */}
                        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                          {topicRec.videos.map((video) => (
                            <a
                              key={video.id}
                              href={video.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="group"
                            >
                              <Card className="glass overflow-hidden hover:shadow-xl transition-all duration-300 hover:scale-105">
                                {/* Thumbnail */}
                                <div className="relative aspect-video bg-muted">
                                  <img
                                    src={video.thumbnail}
                                    alt={video.title}
                                    className="w-full h-full object-cover"
                                    onError={(e) => {
                                      const target = e.target as HTMLImageElement
                                      target.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='180'%3E%3Crect fill='%23374151' width='320' height='180'/%3E%3Ctext fill='%239CA3AF' font-family='sans-serif' font-size='18' x='50%25' y='50%25' text-anchor='middle' dominant-baseline='middle'%3EVideo Thumbnail%3C/text%3E%3C/svg%3E"
                                    }}
                                  />
                                  <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                                    <Play className="h-16 w-16 text-white" />
                                  </div>
                                  <div className="absolute bottom-2 right-2 bg-black/80 text-white text-xs px-2 py-1 rounded">
                                    {video.duration}
                                  </div>
                                </div>

                                {/* Video Info */}
                                <div className="p-4 space-y-2">
                                  <h3 className="font-semibold line-clamp-2 group-hover:text-primary transition-colors">
                                    {video.title}
                                  </h3>
                                  <p className="text-sm text-muted-foreground">
                                    {video.channel}
                                  </p>
                                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                                    <div className="flex items-center gap-1">
                                      <Eye className="h-3 w-3" />
                                      {video.views} views
                                    </div>
                                    <div className="flex items-center gap-1">
                                      <Clock className="h-3 w-3" />
                                      {video.publishedAt}
                                    </div>
                                  </div>
                                </div>
                              </Card>
                            </a>
                          ))}
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </TabsContent>

            {/* Learning Resources Tab */}
            <TabsContent value="resources" className="space-y-6">
              {/* Filters */}
              <Card className="glass p-6">
                <div className="flex flex-wrap gap-4 items-center">
                  <div className="flex items-center gap-2">
                    <Filter className="h-5 w-5 text-muted-foreground" />
                    <span className="font-medium">Filters:</span>
                  </div>
                  
                  <div className="flex gap-2">
                    <span className="text-sm text-muted-foreground">Status:</span>
                    {["all", "pending", "in_progress", "completed"].map((status) => (
                      <Button
                        key={status}
                        variant={filterStatus === status ? "default" : "outline"}
                        size="sm"
                        onClick={() => setFilterStatus(status)}
                      >
                        {status.replace("_", " ").charAt(0).toUpperCase() + status.slice(1).replace("_", " ")}
                      </Button>
                    ))}
                  </div>

                  <div className="flex gap-2">
                    <span className="text-sm text-muted-foreground">Priority:</span>
                    {["all", "high", "medium", "low"].map((priority) => (
                      <Button
                        key={priority}
                        variant={filterPriority === priority ? "default" : "outline"}
                        size="sm"
                        onClick={() => setFilterPriority(priority)}
                      >
                        {priority.charAt(0).toUpperCase() + priority.slice(1)}
                      </Button>
                    ))}
                  </div>
                </div>
              </Card>

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
              ) : (
                <div className="grid md:grid-cols-2 gap-6">
                  {recommendations.map((rec) => (
                    <Card key={rec.id} className="glass p-6 space-y-4 hover:shadow-lg transition-shadow">
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
                            ✓ Completed on {new Date(rec.completed_at || "").toLocaleDateString()}
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
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </main>
    </div>
  )
}
