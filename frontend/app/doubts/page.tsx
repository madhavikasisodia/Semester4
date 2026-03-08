"use client"

import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { MessageSquare, Send, CheckCircle2, Clock, Tag, AlertCircle } from "lucide-react"
import { useState, useEffect } from "react"
import { useAuthStore } from "@/lib/store"
import { useRouter } from "next/navigation"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface Doubt {
  id: number
  title: string
  description: string
  category: string
  tags: string[]
  priority: string
  status: string
  created_at: string
  resolved_at?: string
  response?: string
}

export default function DoubtsPage() {
  const router = useRouter()
  const { user } = useAuthStore()
  const [loading, setLoading] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [doubts, setDoubts] = useState<Doubt[]>([])
  
  // Form state
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [category, setCategory] = useState("")
  const [tags, setTags] = useState("")
  const [priority, setPriority] = useState("medium")
  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  useEffect(() => {
    if (!user) {
      router.push("/login")
      return
    }
    fetchDoubts()
  }, [user])

  const fetchDoubts = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/doubts/my-doubts`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("token")}`,
        },
      })
      if (response.ok) {
        const data = await response.json()
        setDoubts(data)
      }
    } catch (error) {
      console.error("Error fetching doubts:", error)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setSuccess("")

    if (!title.trim() || !description.trim() || !category) {
      setError("Please fill in all required fields")
      return
    }

    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/doubts/submit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("token")}`,
        },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim(),
          category,
          tags: tags.split(",").map(t => t.trim()).filter(t => t),
          priority,
        }),
      })

      if (response.ok) {
        setSuccess("Doubt submitted successfully! Our team will respond soon.")
        setTitle("")
        setDescription("")
        setCategory("")
        setTags("")
        setPriority("medium")
        setShowForm(false)
        fetchDoubts()
      } else {
        const data = await response.json()
        setError(data.detail || "Failed to submit doubt")
      }
    } catch (error) {
      console.error("Error submitting doubt:", error)
      setError("Failed to submit doubt. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case "high": return "text-red-500 bg-red-500/10"
      case "medium": return "text-yellow-500 bg-yellow-500/10"
      case "low": return "text-green-500 bg-green-500/10"
      default: return "text-gray-500 bg-gray-500/10"
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "resolved": return <CheckCircle2 className="w-4 h-4 text-green-500" />
      case "pending": return <Clock className="w-4 h-4 text-yellow-500" />
      default: return <AlertCircle className="w-4 h-4 text-blue-500" />
    }
  }

  return (
    <>
      <Navbar />
      <main className="pt-20 pb-12 min-h-screen">
        <div className="max-w-6xl mx-auto px-4">
          {/* Header */}
          <div className="mb-8">
            <h1 className="text-4xl font-bold mb-4 flex items-center gap-3">
              <MessageSquare className="w-10 h-10 text-accent" />
              Ask Your Doubts
            </h1>
            <p className="text-muted-foreground text-lg">
              Stuck somewhere in your preparation? Submit your doubts and get expert guidance!
            </p>
          </div>

          {/* Submit Button */}
          {!showForm && (
            <Card className="glass p-6 mb-8">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold mb-2">Have a Question?</h2>
                  <p className="text-muted-foreground">
                    Submit your doubt and our experts will help you resolve it
                  </p>
                </div>
                <Button onClick={() => setShowForm(true)} size="lg">
                  <Send className="w-4 h-4 mr-2" />
                  Submit Doubt
                </Button>
              </div>
            </Card>
          )}

          {/* Submission Form */}
          {showForm && (
            <Card className="glass p-6 mb-8">
              <h2 className="text-2xl font-bold mb-6">Submit Your Doubt</h2>
              
              {error && (
                <div className="mb-4 p-4 bg-red-500/10 border border-red-500 rounded-lg text-red-500">
                  {error}
                </div>
              )}
              
              {success && (
                <div className="mb-4 p-4 bg-green-500/10 border border-green-500 rounded-lg text-green-500">
                  {success}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-6">
                <div>
                  <Label htmlFor="title">Title *</Label>
                  <Input
                    id="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Brief summary of your doubt"
                    maxLength={200}
                    required
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    {title.length}/200 characters
                  </p>
                </div>

                <div>
                  <Label htmlFor="description">Description *</Label>
                  <Textarea
                    id="description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Explain your doubt in detail. Include what you've tried and where you're stuck."
                    className="min-h-[150px]"
                    maxLength={2000}
                    required
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    {description.length}/2000 characters
                  </p>
                </div>

                <div className="grid md:grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="category">Category *</Label>
                    <Select value={category} onValueChange={setCategory} required>
                      <SelectTrigger>
                        <SelectValue placeholder="Select category" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="data-structures">Data Structures</SelectItem>
                        <SelectItem value="algorithms">Algorithms</SelectItem>
                        <SelectItem value="system-design">System Design</SelectItem>
                        <SelectItem value="databases">Databases</SelectItem>
                        <SelectItem value="web-development">Web Development</SelectItem>
                        <SelectItem value="programming-languages">Programming Languages</SelectItem>
                        <SelectItem value="devops">DevOps</SelectItem>
                        <SelectItem value="cloud">Cloud Computing</SelectItem>
                        <SelectItem value="interview-tips">Interview Tips</SelectItem>
                        <SelectItem value="career-guidance">Career Guidance</SelectItem>
                        <SelectItem value="other">Other</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div>
                    <Label htmlFor="priority">Priority</Label>
                    <Select value={priority} onValueChange={setPriority}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="low">Low - Can wait</SelectItem>
                        <SelectItem value="medium">Medium - Normal</SelectItem>
                        <SelectItem value="high">High - Urgent</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div>
                  <Label htmlFor="tags">Tags (comma-separated)</Label>
                  <Input
                    id="tags"
                    value={tags}
                    onChange={(e) => setTags(e.target.value)}
                    placeholder="e.g., arrays, sorting, binary-search"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Add relevant tags to help categorize your doubt
                  </p>
                </div>

                <div className="flex gap-3">
                  <Button type="submit" disabled={loading}>
                    {loading ? "Submitting..." : "Submit Doubt"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setShowForm(false)
                      setError("")
                      setSuccess("")
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            </Card>
          )}

          {/* My Doubts */}
          <div>
            <h2 className="text-2xl font-bold mb-6">My Doubts ({doubts.length})</h2>
            
            {doubts.length === 0 ? (
              <Card className="glass p-12 text-center">
                <MessageSquare className="w-16 h-16 mx-auto mb-4 text-muted-foreground" />
                <p className="text-lg text-muted-foreground">
                  No doubts submitted yet. Click "Submit Doubt" to ask your first question!
                </p>
              </Card>
            ) : (
              <div className="space-y-4">
                {doubts.map((doubt) => (
                  <Card key={doubt.id} className="glass p-6 hover:border-accent/50 transition-all">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          {getStatusIcon(doubt.status)}
                          <h3 className="text-xl font-semibold">{doubt.title}</h3>
                        </div>
                        <p className="text-muted-foreground mb-3">{doubt.description}</p>
                      </div>
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${getPriorityColor(doubt.priority)}`}>
                        {doubt.priority}
                      </span>
                    </div>

                    <div className="flex flex-wrap gap-2 mb-3">
                      <span className="px-2 py-1 bg-primary/20 rounded text-xs">
                        {doubt.category}
                      </span>
                      {doubt.tags?.map((tag, i) => (
                        <span key={i} className="px-2 py-1 bg-muted rounded text-xs flex items-center gap-1">
                          <Tag className="w-3 h-3" />
                          {tag}
                        </span>
                      ))}
                    </div>

                    <div className="text-sm text-muted-foreground mb-3">
                      Submitted {new Date(doubt.created_at).toLocaleString()}
                    </div>

                    {doubt.response && (
                      <div className="mt-4 p-4 bg-green-500/5 border border-green-500/20 rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                          <CheckCircle2 className="w-4 h-4 text-green-500" />
                          <span className="font-medium text-green-500">Expert Response</span>
                        </div>
                        <p className="text-sm">{doubt.response}</p>
                        {doubt.resolved_at && (
                          <p className="text-xs text-muted-foreground mt-2">
                            Resolved {new Date(doubt.resolved_at).toLocaleString()}
                          </p>
                        )}
                      </div>
                    )}
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
