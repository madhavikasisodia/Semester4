"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Navbar } from "@/components/navbar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { leetcodeAPI, codeRunnerAPI, type LeetCodeProblem, type JavaExecuteResponse } from "@/lib/api"
import { useAuthStore } from "@/lib/store"
import { ArrowRight, Code, RefreshCw, TerminalSquare } from "lucide-react"

const DEFAULT_CODE = `public class Main {
  public static void main(String[] args) throws Exception {
    java.util.Scanner scanner = new java.util.Scanner(System.in);
    int sum = 0;
    while (scanner.hasNextInt()) {
      sum += scanner.nextInt();
    }
    System.out.println(sum);
  }
}
`

const difficultyBadgeStyles: Record<string, string> = {
  easy: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border border-emerald-500/30",
  medium: "bg-amber-500/15 text-amber-600 dark:text-amber-300 border border-amber-500/30",
  hard: "bg-rose-500/15 text-rose-600 dark:text-rose-300 border border-rose-500/30",
}

export default function PracticeCoding() {
  const router = useRouter()
  const { user } = useAuthStore()
  const [difficulty, setDifficulty] = useState("medium")
  const [question, setQuestion] = useState<LeetCodeProblem | null>(null)
  const [questionLoading, setQuestionLoading] = useState(false)
  const [questionError, setQuestionError] = useState<string | null>(null)

  const [code, setCode] = useState(DEFAULT_CODE)
  const [stdin, setStdin] = useState("1 2 3 4 5")
  const [runResult, setRunResult] = useState<JavaExecuteResponse | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    if (!user) {
      router.push("/login")
    }
  }, [user, router])

  const fetchRandomQuestion = useCallback(async () => {
    setQuestionLoading(true)
    setQuestionError(null)
    try {
      const items = await leetcodeAPI.getProblems(difficulty, 80)
      if (!items.length) {
        setQuestion(null)
        setQuestionError("No LeetCode problems found for this difficulty.")
        return
      }
      const item = items[Math.floor(Math.random() * items.length)]
      setQuestion(item)
    } catch (error) {
      setQuestionError("Unable to load a practice question right now.")
      setQuestion(null)
    } finally {
      setQuestionLoading(false)
    }
  }, [difficulty])

  useEffect(() => {
    fetchRandomQuestion()
  }, [fetchRandomQuestion])

  const handleRun = async () => {
    setRunning(true)
    setRunError(null)
    setRunResult(null)
    try {
      const result = await codeRunnerAPI.executeJava(code, stdin)
      setRunResult(result)
    } catch (error: any) {
      setRunError(error?.response?.data?.detail || "Execution failed. Check your server logs for details.")
    } finally {
      setRunning(false)
    }
  }

  const difficultyLabel = difficulty.charAt(0).toUpperCase() + difficulty.slice(1)
  const difficultyStyle = difficultyBadgeStyles[difficulty] ?? ""

  const outputSummary = useMemo(() => {
    if (!runResult) return ""
    if (!runResult.compile_success) return "Compilation failed"
    return runResult.stderr ? "Runtime error" : "Run completed"
  }, [runResult])

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(124,58,237,0.15),_transparent_55%),radial-gradient(circle_at_20%_40%,_rgba(16,185,129,0.12),_transparent_50%),radial-gradient(circle_at_80%_30%,_rgba(14,165,233,0.12),_transparent_45%)]">
      <Navbar />
      <main className="pt-24 pb-12 px-4">
        <div className="mx-auto w-full max-w-6xl space-y-6">
          <section className="flex flex-col gap-4 rounded-3xl border border-border/60 bg-background/60 p-6 shadow-lg shadow-black/5 backdrop-blur">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-2">
                <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/80 px-3 py-1 text-xs uppercase tracking-[0.2em] text-muted-foreground">
                  <Code className="h-3.5 w-3.5" />
                  Practice Arena
                </div>
                <h1 className="text-3xl font-semibold tracking-tight">
                  Practice Coding Questions with a Java Runner
                </h1>
                <p className="text-sm text-muted-foreground max-w-2xl">
                  Pick a prompt, run Java code instantly on the server, and review output like a mini LeetCode desk.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Select value={difficulty} onValueChange={setDifficulty}>
                  <SelectTrigger className="w-36">
                    <SelectValue placeholder="Difficulty" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="easy">Easy</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="hard">Hard</SelectItem>
                  </SelectContent>
                </Select>
                <Button variant="outline" onClick={fetchRandomQuestion} disabled={questionLoading}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  {questionLoading ? "Loading" : "New Question"}
                </Button>
              </div>
            </div>
          </section>

          <section className="grid gap-6 xl:grid-cols-[1.1fr_1.4fr]">
            <Card className="p-6 border-border/60 bg-background/70 shadow-md shadow-black/5">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Problem Statement</h2>
                <Badge className={difficultyStyle}>{difficultyLabel}</Badge>
              </div>
              <div className="mt-4 space-y-4 text-sm text-muted-foreground">
                {questionError && <p className="text-destructive">{questionError}</p>}
                {!questionError && questionLoading && <p>Loading question...</p>}
                {!questionLoading && question ? (
                  <>
                    <div className="space-y-2">
                      <p className="text-base font-semibold text-foreground">{question.title}</p>
                      <p>Use the editor to solve the problem, then open the full prompt on LeetCode.</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">LeetCode</Badge>
                      {question.acceptance_rate !== null && question.acceptance_rate !== undefined && (
                        <Badge variant="secondary">Acceptance {question.acceptance_rate}%</Badge>
                      )}
                    </div>
                    {question.link && (
                      <Link href={question.link} target="_blank" className="inline-flex items-center gap-2 text-primary">
                        View full prompt
                        <ArrowRight className="h-4 w-4" />
                      </Link>
                    )}
                  </>
                ) : null}
              </div>
            </Card>

            <Card className="p-6 border-border/60 bg-background/70 shadow-md shadow-black/5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Java Editor</h2>
                  <p className="text-xs text-muted-foreground">Class name must be Main</p>
                </div>
                <Button onClick={handleRun} disabled={running}>
                  {running ? "Running..." : "Run"}
                </Button>
              </div>
              <div className="mt-4 space-y-4">
                <Textarea
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  rows={18}
                  className="font-mono text-sm bg-background/80"
                />
                <div className="grid gap-3 lg:grid-cols-[1fr_1.2fr]">
                  <div className="space-y-2">
                    <Label className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Input</Label>
                    <Textarea
                      value={stdin}
                      onChange={(event) => setStdin(event.target.value)}
                      rows={5}
                      className="font-mono text-sm bg-background/80"
                      placeholder="Provide stdin here"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Output</Label>
                    <div className="min-h-[126px] rounded-lg border border-border/60 bg-background/80 p-3 font-mono text-sm">
                      {runError && <p className="text-destructive">{runError}</p>}
                      {!runError && runResult ? (
                        <div className="space-y-3">
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <TerminalSquare className="h-3.5 w-3.5" />
                            <span>{outputSummary}</span>
                            <span>·</span>
                            <span>{runResult.time_ms} ms</span>
                          </div>
                          {runResult.compile_output && (
                            <pre className="whitespace-pre-wrap text-amber-500/80">
                              {runResult.compile_output}
                            </pre>
                          )}
                          {runResult.stdout && (
                            <pre className="whitespace-pre-wrap text-foreground">{runResult.stdout}</pre>
                          )}
                          {runResult.stderr && (
                            <pre className="whitespace-pre-wrap text-destructive">{runResult.stderr}</pre>
                          )}
                          {!runResult.stdout && !runResult.stderr && !runResult.compile_output && (
                            <p className="text-muted-foreground">No output</p>
                          )}
                        </div>
                      ) : (
                        <p className="text-muted-foreground">Run your solution to see output.</p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          </section>
        </div>
      </main>
    </div>
  )
}
