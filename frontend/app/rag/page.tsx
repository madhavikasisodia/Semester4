"use client"

import { useMemo, useState } from "react"
import { Navbar } from "@/components/navbar"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Database, Search, Sparkles, Loader2, AlertCircle } from "lucide-react"
import { api } from "@/lib/api"

interface RagSource {
  source: string
  topic?: string | null
  similarity?: number
  excerpt?: string
}

interface RagResponse {
  response: string
  suggestions?: string[]
  sources?: RagSource[]
  confidence?: number
  rag_used?: boolean
  difficulty_level?: string
  practice_question?: string | null
  section?: string
}

export default function RagSystemPage() {
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState<RagResponse | null>(null)

  const confidenceLabel = useMemo(() => {
    const raw = result?.confidence ?? 0
    const pct = Math.round(Math.min(Math.max(raw, 0), 1) * 100)
    return `${pct}%`
  }, [result?.confidence])

  const handleRun = async () => {
    if (!query.trim() || loading) return
    setLoading(true)
    setError("")
    try {
      const response = await api.post<RagResponse>("/doubts/chat", {
        message: query.trim(),
        conversation_history: [],
        weak_topics: [],
        readiness_score: 0,
        learning_goal: "RAG insights",
      })
      setResult(response.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to fetch RAG response.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(16,185,129,0.12),_transparent_55%),radial-gradient(circle_at_20%_40%,_rgba(59,130,246,0.1),_transparent_50%),radial-gradient(circle_at_80%_30%,_rgba(14,165,233,0.1),_transparent_45%)]">
      <Navbar />
      <main className="container mx-auto px-4 py-10">
        <div className="mb-8 rounded-3xl border border-border/60 bg-background/60 p-6 shadow-lg shadow-black/5 backdrop-blur">
          <h1 className="text-3xl font-semibold tracking-tight flex items-center gap-3">
            <Database className="h-7 w-7 text-emerald-500" />
            Insights
          </h1>
          <p className="text-sm text-muted-foreground mt-2">
            Retrieval insights, sources, and response quality tracking.
          </p>
        </div>

        <Card className="p-6 border-border/60 bg-background/70 shadow-md shadow-black/5 mb-6">
          <div className="flex items-center gap-3 mb-4">
            <Search className="h-5 w-5 text-blue-500" />
            <h2 className="text-lg font-semibold">Run a RAG Query</h2>
          </div>
          <div className="space-y-4">
            <Input
              placeholder="Ask a question to test retrieval and generation..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="flex items-center gap-3">
              <Button onClick={handleRun} disabled={loading || !query.trim()} className="gap-2">
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {loading ? "Running" : "Run RAG"}
              </Button>
              {error && (
                <span className="text-sm text-red-500 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4" />
                  {error}
                </span>
              )}
            </div>
          </div>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="p-6 border-border/60 bg-background/70 shadow-md shadow-black/5 lg:col-span-2">
            <div className="flex items-center gap-3 mb-3">
              <Sparkles className="h-5 w-5 text-amber-500" />
              <h2 className="text-lg font-semibold">Response Quality</h2>
            </div>
            {result ? (
              <div className="space-y-4">
                <div className="rounded-lg border border-border/60 bg-background/80 p-4">
                  <p className="text-sm font-medium text-muted-foreground">Answer</p>
                  <p className="mt-2 text-sm whitespace-pre-wrap text-foreground">{result.response}</p>
                </div>
                {result.practice_question && (
                  <div className="rounded-lg border border-border/60 bg-background/80 p-4">
                    <p className="text-sm font-medium text-muted-foreground">Practice Question</p>
                    <p className="mt-2 text-sm text-foreground">{result.practice_question}</p>
                  </div>
                )}
                {result.suggestions && result.suggestions.length > 0 && (
                  <div className="rounded-lg border border-border/60 bg-background/80 p-4">
                    <p className="text-sm font-medium text-muted-foreground">Suggestions</p>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground">
                      {result.suggestions.map((suggestion) => (
                        <li key={suggestion}>{suggestion}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Run a query to view the generated response.</p>
            )}
          </Card>

          <Card className="p-6 border-border/60 bg-background/70 shadow-md shadow-black/5">
            <div className="flex items-center gap-3 mb-3">
              <Database className="h-5 w-5 text-emerald-500" />
              <h2 className="text-lg font-semibold">RAG Analytics</h2>
            </div>
            {result ? (
              <div className="space-y-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Confidence</span>
                  <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border border-emerald-500/30">
                    {confidenceLabel}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">RAG Used</span>
                  <Badge className={result.rag_used ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border border-emerald-500/30" : "bg-amber-500/15 text-amber-600 dark:text-amber-300 border border-amber-500/30"}>
                    {result.rag_used ? "Yes" : "Fallback"}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Difficulty</span>
                  <Badge className="bg-blue-500/15 text-blue-600 dark:text-blue-300 border border-blue-500/30">
                    {result.difficulty_level || "n/a"}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Sources</span>
                  <span className="text-foreground font-medium">{result.sources?.length || 0}</span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Analytics will appear after a query.</p>
            )}
          </Card>
        </div>

        <Card className="p-6 border-border/60 bg-background/70 shadow-md shadow-black/5 mt-6">
          <div className="flex items-center gap-3 mb-3">
            <Search className="h-5 w-5 text-blue-500" />
            <h2 className="text-lg font-semibold">Retrieval Focus</h2>
          </div>
          {result?.sources && result.sources.length > 0 ? (
            <div className="space-y-3">
              {result.sources.map((source) => (
                <div key={source.source} className="rounded-lg border border-border/60 bg-background/80 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-foreground">{source.source}</p>
                      {source.topic && (
                        <p className="text-xs text-muted-foreground">Topic: {source.topic}</p>
                      )}
                    </div>
                    {typeof source.similarity === "number" && (
                      <Badge className="bg-blue-500/15 text-blue-600 dark:text-blue-300 border border-blue-500/30">
                        Similarity {Math.round(source.similarity * 100)}%
                      </Badge>
                    )}
                  </div>
                  {source.excerpt && (
                    <p className="mt-3 text-sm text-muted-foreground">{source.excerpt}</p>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No retrieval sources yet.</p>
          )}
        </Card>
      </main>
    </div>
  )
}
