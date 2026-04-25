"use client"

import { Navbar } from "@/components/navbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Brain, TrendingUp, AlertCircle, Send, Award, CheckCircle, Video, Mic, StopCircle } from "lucide-react"
import { useState, useEffect, useRef } from "react"
import { interviewAPI, type Persona, type InterviewSession, type InterviewReport } from "@/lib/api"
import { Textarea } from "@/components/ui/textarea"

// Try multiple storage keys for auth token (different login methods might use different keys)
const getStoredAccessToken = (): string | null => {
  if (typeof window === "undefined") return null
  return (
    localStorage.getItem("auth_token") ||
    localStorage.getItem("token") ||
    localStorage.getItem("access_token")
  )
}

// Type guard to identify axios-like errors from API calls
const isAxiosLikeError = (err: any): err is {
  message?: string
  code?: string
  config?: { url?: string; method?: string }
  response?: { status?: number; data?: any }
} => {
  return !!err && typeof err === "object" && ("response" in err || "config" in err || "code" in err)
}

// Parse various error types and provide user-friendly messages
const formatErrorMessage = (err: any): string => {
  if (typeof err === 'string') return err

  if (!isAxiosLikeError(err)) {
    return err?.message || "An unexpected error occurred"
  }
  
  const status = err.response?.status
  const requestUrl = String(err.config?.url || "")

  if (err.code === "ERR_NETWORK") {
    return "Cannot reach backend server. Ensure FastAPI is running on http://localhost:8000 and CORS allows frontend origin."
  }

  if (status === 401) {
    return "Session expired or not logged in. Please log in again and retry."
  }

  if ((status === 404 || status === 405) && requestUrl.includes("/interview/transcribe")) {
    return "Whisper transcription endpoint is unavailable. Please restart backend server to load the latest routes."
  }

  // Check if it's a FastAPI validation error
  if (Array.isArray(err.response?.data?.detail)) {
    const details = err.response.data.detail.map((e: any) => 
      `${e.loc.join('.')} - ${e.msg} (${e.type})`
    ).join('; ')
    return `Validation Error: ${details}`
  }
  
  // Check if detail is a string
  if (typeof err.response?.data?.detail === 'string') {
    return err.response.data.detail
  }

  if (typeof err.response?.data === "string" && err.response.data.trim()) {
    return err.response.data
  }

  if (status) {
    return `Request failed (${status}). Please try again.`
  }
  
  // Fallback to error message or generic message
  return err.message || "An error occurred"
}

export default function InterviewPage() {
  // Interview state
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedPersona, setSelectedPersona] = useState<string | null>(null)
  const [sessionStarted, setSessionStarted] = useState(false)
  const [currentSession, setCurrentSession] = useState<InterviewSession | null>(null)
  const [interviewComplete, setInterviewComplete] = useState(false)
  const [finalReport, setFinalReport] = useState<InterviewReport | null>(null)
  const [currentQuestion, setCurrentQuestion] = useState<{ title: string; text?: string; difficulty?: string } | null>(null)
  
  // Answer & feedback state
  const [answer, setAnswer] = useState("")
  const [currentFeedback, setCurrentFeedback] = useState<any>(null)
  
  // Interview setup form fields
  const [candidateName, setCandidateName] = useState("")
  const [targetRole, setTargetRole] = useState("")
  const [interviewType, setInterviewType] = useState("technical")
  const [difficulty, setDifficulty] = useState("medium")
  
  // Recording and media state
  const [isRecording, setIsRecording] = useState(false)
  const [recordingMode, setRecordingMode] = useState<"text" | "video">("text")
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null)
  const [recordedChunks, setRecordedChunks] = useState<Blob[]>([])
  const [recordingStartTime, setRecordingStartTime] = useState<number>(0)
  const [recordingDuration, setRecordingDuration] = useState<number>(0)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [liveRecordingSeconds, setLiveRecordingSeconds] = useState(0)
  
  // API & UI state
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [syncingSession, setSyncingSession] = useState(false)
  
  const videoRef = useRef<HTMLVideoElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)

  const syncSessionStatus = async (sessionId: string) => {
    // Poll backend for latest interview status
    try {
      setSyncingSession(true)
      const status = await interviewAPI.getInterviewStatus(sessionId)

      setCurrentSession((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          question_count: status.question_count || prev.question_count,
          total_questions: status.question_count || prev.total_questions,
          current_question_number: Math.min(
            status.question_count || prev.question_count || 1,
            (status.current_question_index || 0) + 1
          ),
        }
      })

      if (status.current_question) {
        setCurrentQuestion({
          title: status.current_question.question || "Question",
          text: status.current_question.question_text || status.current_question.question || "",
          difficulty: status.current_question.difficulty,
        })
      }

      if (status.status === "completed") {
        const report = await interviewAPI.getInterviewReport(sessionId)
        setFinalReport(report)
        setInterviewComplete(true)
        setCurrentQuestion(null)
        stopMediaStream()
      }
    } catch (err: any) {
      setError(formatErrorMessage(err))
    } finally {
      setSyncingSession(false)
    }
  }

  useEffect(() => {
    const fetchPersonas = async () => {
      try {
        const data = await interviewAPI.getPersonas()
        setPersonas(data)
      } catch (err: any) {
        console.error("Failed to fetch personas:", err)
        setError(formatErrorMessage(err))
      }
    }
    fetchPersonas()
  }, [])

  useEffect(() => {
    // Restore any existing active interview session on page load
    const restoreActiveSession = async () => {
      if (!getStoredAccessToken()) return

      try {
        const active = await interviewAPI.getActiveSessions()
        const live = active.sessions.find((s) => s.status === "active")
        if (!live) return

        setSessionStarted(true)
        setInterviewComplete(false)
        setCurrentFeedback(null)
        setFinalReport(null)
        setCurrentSession({
          session_id: live.session_id,
          persona: "",
          question_count: Math.max(1, live.questions_answered + 1),
          current_question_number: Math.max(1, live.questions_answered + 1),
          current_question: "Resuming your interview...",
          difficulty: "medium",
          start_time: live.start_time,
          interviewer: { name: "AI Interviewer" },
        })
        setCurrentQuestion({
          title: "Resuming your interview...",
          text: "Fetching your latest question",
        })

        await syncSessionStatus(live.session_id)
      } catch {
        // Ignore restore failures to avoid blocking normal startup.
      }
    }

    restoreActiveSession()
  }, [])

  const startInterview = async (persona: string) => {
    // Validate required fields and create new interview session
    if (!candidateName.trim() || !targetRole.trim()) {
      setError("Please enter your name and target role")
      return
    }

    if (!getStoredAccessToken()) {
      setError("Please log in first to start an interview session.")
      return
    }
    
    setLoading(true)
    setError(null)
    try {
      console.log("Starting interview with:", {
        persona,
        candidateName,
        targetRole,
        interviewType,
        difficulty
      })
      
      const session = await interviewAPI.startInterview(
        persona,
        candidateName,
        targetRole,
        interviewType,
        difficulty,
        30
      )
      const personaMeta = personas.find((p) => p.persona_id === persona)
      setCurrentSession({
        ...session,
        interviewer: session.interviewer || personaMeta,
      })
      setCurrentQuestion({
        title: session.current_question,
        text: session.current_question_text || session.current_question,
        difficulty: session.current_question_difficulty,
      })
      setSelectedPersona(persona)
      setSessionStarted(true)
    } catch (err: any) {
      if (isAxiosLikeError(err)) {
        console.error("Interview start error", {
          message: err.message,
          code: err.code,
          status: err.response?.status,
          url: err.config?.url,
          method: err.config?.method,
          data: err.response?.data,
        })
      } else {
        console.error("Interview start error:", err)
      }
      setError(formatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const resetInterview = () => {
    setSessionStarted(false)
    setCurrentSession(null)
    setSelectedPersona(null)
    setAnswer("")
    setCurrentFeedback(null)
    setInterviewComplete(false)
    setFinalReport(null)
    setCurrentQuestion(null)
    setIsTranscribing(false)
    stopMediaStream()
  }

  // Start camera and microphone
  const startMediaCapture = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480 },
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        }
      })
      
      setMediaStream(stream)
      
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
      
      setRecordingMode("video")
    } catch (err: any) {
      setError("Camera/microphone access denied. Please enable permissions.")
      console.error("Media error:", err)
    }
  }

  // Stop all media streams
  const stopMediaStream = () => {
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop())
      setMediaStream(null)
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }

  // Start recording audio answer
  const startRecording = () => {
    if (!mediaStream) {
      setError("Please enable camera first")
      return
    }

    // Extract audio track and create audio-only stream for recording
    const audioTracks = mediaStream.getAudioTracks()
    if (audioTracks.length === 0) {
      setError("Microphone track not found. Please allow microphone access and try again.")
      return
    }

    // Use best supported audio codec for compatibility
    const audioOnlyStream = new MediaStream(audioTracks)
    const preferredMimeTypes = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
    ]
    const selectedMimeType =
      preferredMimeTypes.find((mime) => MediaRecorder.isTypeSupported(mime)) || ""
    const recorder = selectedMimeType
      ? new MediaRecorder(audioOnlyStream, { mimeType: selectedMimeType })
      : new MediaRecorder(audioOnlyStream)
    
    const chunks: Blob[] = []
    
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        chunks.push(e.data)
      }
    }
    
    recorder.onstop = async () => {
      setRecordedChunks(chunks)
      if (chunks.length === 0) {
        setError("No audio captured. Please record your answer again.")
        return
      }

      const blobType = recorder.mimeType || "audio/webm"
      const extension = blobType.includes("ogg") ? "ogg" : "webm"
      const blob = new Blob(chunks, { type: blobType })
      if (!blob.size) {
        setError("Recording captured no audio data. Please allow microphone access and try again.")
        return
      }
      const file = new File([blob], `answer-${Date.now()}.${extension}`, {
        type: blob.type || "audio/webm",
      })

      setIsTranscribing(true)
      setError(null)
      try {
        const transcription = await interviewAPI.transcribeAudio(file)
        const transcript = transcription.text?.trim() || ""
        if (!transcript) {
          setError(transcription.warning || "Whisper could not detect speech. Please try recording again.")
          return
        }
        setAnswer(transcript)
        if (transcription.warning) {
          setError(transcription.warning)
        }
      } catch (err: any) {
        console.error("Transcription error:", err)
        setError(formatErrorMessage(err))
      } finally {
        setIsTranscribing(false)
      }
    }
    
    mediaRecorderRef.current = recorder
    recorder.start()
    setIsRecording(true)
    setRecordingStartTime(Date.now())
    setLiveRecordingSeconds(0)
    setAnswer("") // Clear previous answer
  }

  // Stop recording
  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
      
      const duration = (Date.now() - recordingStartTime) / 1000
      setRecordingDuration(duration)
    }
  }

  // Submit answer with video duration and handle next question or completion
  const submitAnswer = async () => {
    if (!currentSession || !answer.trim()) {
      setError("Please record an answer first")
      return
    }
    
    setLoading(true)
    setError(null)
    
    try {
      const feedback = await interviewAPI.submitAnswer(
        currentSession.session_id,
        answer,
        recordingDuration > 0 ? recordingDuration : undefined
      )
      
      setCurrentFeedback(feedback)
      setAnswer("")
      setRecordedChunks([])
      setRecordingDuration(0)
      
      if (feedback.status === "completed") {
        const report = await interviewAPI.getInterviewReport(currentSession.session_id)
        setFinalReport(report)
        setInterviewComplete(true)
        setCurrentQuestion(null)
        stopMediaStream()
      } else if (feedback.next_question) {
        setCurrentSession((prev: InterviewSession | null) => {
          if (!prev) return prev
          const totalQuestions = prev.question_count || prev.total_questions || feedback.total_questions_asked
          return {
            ...prev,
            current_question_number: Math.min(totalQuestions, feedback.question_number + 1),
            question_count: totalQuestions,
          }
        })
        setCurrentQuestion({
          title: feedback.next_question.question,
          text: feedback.next_question.question_text || feedback.next_question.question,
          difficulty: feedback.next_question.difficulty,
        })
      } else {
        await syncSessionStatus(currentSession.session_id)
      }
    } catch (err: any) {
      console.error("Submit error:", err)
      setError(formatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  // Text-to-speech for questions
  const speakQuestion = (text: string) => {
    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = 0.9
      utterance.pitch = 1
      utterance.volume = 1
      window.speechSynthesis.cancel() // Stop any ongoing speech
      window.speechSynthesis.speak(utterance)
    }
  }

  // Auto-start camera and microphone when interview begins
  useEffect(() => {
    if (sessionStarted && !interviewComplete && recordingMode === "text") {
      startMediaCapture()
    }
  }, [sessionStarted])

  useEffect(() => {
    // Auto-speak new questions after a short delay
    if (!sessionStarted || interviewComplete || !currentQuestion) {
      return
    }
    const timer = setTimeout(() => {
      speakQuestion(currentQuestion.text || currentQuestion.title)
    }, 800)
    return () => clearTimeout(timer)
  }, [sessionStarted, interviewComplete, currentQuestion?.title, currentQuestion?.text])

  useEffect(() => {
    // Update recording duration every 500ms for UI display
    if (!isRecording) return

    const timer = window.setInterval(() => {
      setLiveRecordingSeconds(Math.max(0, Math.floor((Date.now() - recordingStartTime) / 1000)))
    }, 500)

    return () => window.clearInterval(timer)
  }, [isRecording, recordingStartTime])

  useEffect(() => {
    // Poll session status periodically to check if interview is complete
    if (!sessionStarted || interviewComplete || !currentSession?.session_id) return

    const intervalId = window.setInterval(() => {
      if (!loading && !isTranscribing) {
        void syncSessionStatus(currentSession.session_id)
      }
    }, 2500)

    return () => window.clearInterval(intervalId)
  }, [sessionStarted, interviewComplete, currentSession?.session_id, loading, isTranscribing])

  const isAnswerCorrect = currentFeedback?.evaluation?.is_correct ?? false
  const matchedConcepts = currentFeedback?.evaluation?.matched_concepts ?? []
  const missingConcepts = currentFeedback?.evaluation?.missing_concepts ?? []
  const coveragePercent =
    currentFeedback?.evaluation?.coverage_ratio !== undefined && currentFeedback?.evaluation?.coverage_ratio !== null
      ? Math.round((currentFeedback.evaluation.coverage_ratio || 0) * 100)
      : null
  const expectedComplexity = currentFeedback?.evaluation?.expected_complexity
  const expectedComplexityLabel = expectedComplexity
    ? [expectedComplexity.time, expectedComplexity.space].filter(Boolean).join(" • ")
    : ""

  return (
    <div className="min-h-screen bg-background">
      <Navbar />
      
      <main className="container mx-auto px-4 py-8">
        {!sessionStarted ? (
          // Pre-interview setup: Select persona and configure interview
          <div className="max-w-6xl mx-auto space-y-8">
            <div className="text-center space-y-4">
              <h1 className="text-4xl font-bold">AI Mock Interview</h1>
              <p className="text-xl text-muted-foreground">
                Choose your interviewer persona and start practicing
              </p>
            </div>

            {error && (
              <Card className="p-4 bg-destructive/10 border-destructive">
                <div className="flex items-center gap-2 text-destructive">
                  <AlertCircle className="h-5 w-5" />
                  <p>{error}</p>
                </div>
              </Card>
            )}

            {/* Interview Setup Form */}
            <Card className="p-6 max-w-2xl mx-auto space-y-4">
              <h2 className="text-2xl font-semibold">Interview Setup</h2>
              
              {/* Collect candidate information and interview preferences */}
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Your Name</label>
                  <input
                    type="text"
                    value={candidateName}
                    onChange={(e) => setCandidateName(e.target.value)}
                    placeholder="Enter your name"
                    className="w-full px-3 py-2 border rounded-md"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Target Role</label>
                  <input
                    type="text"
                    value={targetRole}
                    onChange={(e) => setTargetRole(e.target.value)}
                    placeholder="e.g., Software Engineer, Product Manager"
                    className="w-full px-3 py-2 border rounded-md"
                  />
                </div>

                <div className="grid md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Interview Type</label>
                    <select
                      value={interviewType}
                      onChange={(e) => setInterviewType(e.target.value)}
                      className="w-full px-3 py-2 border rounded-md"
                    >
                      <option value="technical">Technical</option>
                      <option value="behavioral">Behavioral</option>
                      <option value="hr_screening">HR Screening</option>
                      <option value="system_design">System Design</option>
                      <option value="coding">Coding</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-2">Difficulty</label>
                    <select
                      value={difficulty}
                      onChange={(e) => setDifficulty(e.target.value)}
                      className="w-full px-3 py-2 border rounded-md"
                    >
                      <option value="easy">Easy</option>
                      <option value="medium">Medium</option>
                      <option value="hard">Hard</option>
                    </select>
                  </div>
                </div>
              </div>
            </Card>

            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
              {personas.map((persona, index) => (
                <Card key={persona.persona_id || `persona-${index}`} className="p-6 space-y-4 hover:shadow-lg transition-shadow">
                  <div className="flex items-center gap-3">
                    <Brain className="h-8 w-8 text-primary" />
                    <h3 className="text-xl font-semibold">{persona.name}</h3>
                  </div>
                  
                  <p className="text-muted-foreground">{persona.description}</p>
                  
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Communication Style:</span>
                      <span className="font-medium">{persona.communication_style || 'Professional'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Tone:</span>
                      <span className="font-medium capitalize">{persona.tone || 'Professional'}</span>
                    </div>
                  </div>
                  
                  <Button 
                    onClick={() => startInterview(persona.persona_id)}
                    className="w-full"
                    disabled={loading || !candidateName.trim() || !targetRole.trim()}
                  >
                    {loading && selectedPersona === persona.persona_id ? "Starting..." : "Start Interview"}
                  </Button>
                </Card>
              ))}
            </div>
          </div>
        ) : interviewComplete && finalReport ? (
          // Display interview results and performance metrics
          <div className="max-w-4xl mx-auto space-y-8">
            <div className="text-center space-y-4">
              <div className="flex justify-center">
                <Award className="h-16 w-16 text-primary" />
              </div>
              <h1 className="text-4xl font-bold">Interview Complete!</h1>
              <p className="text-xl text-muted-foreground">
                Here's your performance report
              </p>
            </div>

            <Card className="p-8 space-y-6">
              <div className="grid md:grid-cols-4 gap-6 text-center">
                <div className="space-y-2">
                  <p className="text-muted-foreground">Overall Score</p>
                  <p className="text-4xl font-bold text-primary">
                    {finalReport.overall_score.toFixed(1)}%
                  </p>
                </div>
                <div className="space-y-2">
                  <p className="text-muted-foreground">Questions Answered</p>
                  <p className="text-4xl font-bold">
                    {finalReport.questions_answered || finalReport.total_questions}
                  </p>
                </div>
                {typeof finalReport.correct_answers === "number" && (
                  <div className="space-y-2">
                    <p className="text-muted-foreground">Correct Answers</p>
                    <p className="text-4xl font-bold text-green-600">
                      {finalReport.correct_answers}/{finalReport.total_questions}
                    </p>
                  </div>
                )}
                <div className="space-y-2">
                  <p className="text-muted-foreground">Average Confidence</p>
                  <p className="text-4xl font-bold text-green-600">
                    {finalReport.average_confidence ? finalReport.average_confidence.toFixed(1) : '0.0'}%
                  </p>
                </div>
              </div>

              <div className="space-y-4">
                <h3 className="text-xl font-semibold flex items-center gap-2">
                  <TrendingUp className="h-5 w-5" />
                  Strengths
                </h3>
                <ul className="space-y-2">
                  {finalReport.strengths.map((strength, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <CheckCircle className="h-5 w-5 text-green-600 mt-0.5 shrink-0" />
                      <span>{strength}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="space-y-4">
                <h3 className="text-xl font-semibold flex items-center gap-2">
                  <AlertCircle className="h-5 w-5" />
                  Areas for Improvement
                </h3>
                <ul className="space-y-2">
                  {finalReport.improvement_areas.map((improvement: string, idx: number) => (
                    <li key={idx} className="flex items-start gap-2">
                      <AlertCircle className="h-5 w-5 text-orange-600 mt-0.5 shrink-0" />
                      <span>{improvement}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="space-y-4">
                <h3 className="text-xl font-semibold">Recommendations</h3>
                <ul className="space-y-2 list-disc list-inside text-muted-foreground">
                  {finalReport.recommended_practice.map((rec, idx) => (
                    <li key={idx}>{rec}</li>
                  ))}
                </ul>
              </div>

              <div className="flex gap-4">
                <Button onClick={resetInterview} className="flex-1">
                  Start New Interview
                </Button>
                <Button variant="outline" className="flex-1">
                  View Detailed Analytics
                </Button>
              </div>
            </Card>
          </div>
        ) : (
          // Interview Session Screen
          <div className="max-w-4xl mx-auto space-y-8">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold">Mock Interview Session</h1>
                <p className="text-muted-foreground">
                  Question {currentSession?.current_question_number || 1} of {currentSession?.question_count || currentSession?.total_questions || 1}
                </p>
                {syncingSession && (
                  <p className="text-xs text-muted-foreground mt-1">Syncing live session...</p>
                )}
              </div>
              <Button variant="outline" onClick={resetInterview}>
                End Interview
              </Button>
            </div>

            {error && (
              <Card className="p-4 bg-destructive/10 border-destructive">
                <div className="flex items-center gap-2 text-destructive">
                  <AlertCircle className="h-5 w-5" />
                  <p>{error}</p>
                </div>
              </Card>
            )}

            {currentSession && (
              <>
                {/* Video Interview Interface */}
                <div className="grid md:grid-cols-2 gap-6 mb-6">
                  {/* Your Video */}
                  <Card className="p-4">
                    <h3 className="text-sm font-medium mb-2">Your Video</h3>
                    <video
                      ref={videoRef}
                      autoPlay
                      muted
                      className="w-full rounded-lg bg-black"
                      style={{ maxHeight: '300px' }}
                    />
                    {!mediaStream && (
                      <Button onClick={startMediaCapture} className="w-full mt-2">
                        <Video className="h-4 w-4 mr-2" />
                        Enable Camera
                      </Button>
                    )}
                  </Card>

                  {/* Interviewer Avatar */}
                  <Card className="p-4 flex flex-col items-center justify-center bg-linear-to-br from-primary/10 to-primary/5">
                    <Brain className="h-24 w-24 text-primary mb-4" />
                    <h3 className="text-lg font-semibold">{currentSession.interviewer?.name || "AI Interviewer"}</h3>
                    <p className="text-sm text-muted-foreground">{currentSession.interviewer?.tone || "Professional"}</p>
                  </Card>
                </div>

                {/* Question Card */}
                <Card className="p-6 space-y-4">
                  <div className="flex items-start gap-3">
                    <Brain className="h-6 w-6 text-primary mt-1" />
                    <div className="flex-1">
                      <p className="text-sm text-muted-foreground mb-2">Question {currentSession.current_question_number || 1}:</p>
                      <p className="text-lg font-medium">
                        {currentQuestion?.text || currentQuestion?.title || "The interviewer is preparing your next prompt..."}
                      </p>
                      {currentQuestion?.difficulty && (
                        <p className="text-sm text-muted-foreground mt-2">
                          Difficulty: <span className="font-medium capitalize">{currentQuestion.difficulty}</span>
                        </p>
                      )}
                    </div>
                  </div>
                </Card>

                {/* Answer Section with Recording */}
                <Card className="p-6 space-y-4">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium">Your Answer (Voice Transcription):</label>
                    {isRecording && (
                      <span className="text-sm text-red-600 flex items-center gap-2">
                        <span className="h-2 w-2 bg-red-600 rounded-full animate-pulse"></span>
                        Recording: {liveRecordingSeconds}s
                      </span>
                    )}
                    {!isRecording && isTranscribing && (
                      <span className="text-sm text-primary">Transcribing with Whisper...</span>
                    )}
                  </div>
                  
                  <Textarea
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    placeholder="Click 'Start Recording' to speak your answer, or type here..."
                    className="min-h-[150px]"
                    readOnly={isRecording}
                  />

                  <div className="flex gap-3">
                    {!isRecording ? (
                      <Button 
                        onClick={startRecording}
                        disabled={!mediaStream || loading || isTranscribing}
                        className="flex-1"
                        variant="default"
                      >
                        <Mic className="h-4 w-4 mr-2" />
                        Start Recording Answer
                      </Button>
                    ) : (
                      <Button 
                        onClick={stopRecording}
                        className="flex-1"
                        variant="destructive"
                      >
                        <StopCircle className="h-4 w-4 mr-2" />
                        Stop Recording
                      </Button>
                    )}
                    
                    <Button 
                      onClick={submitAnswer}
                      disabled={loading || isTranscribing || !answer.trim() || isRecording}
                      className="flex-1"
                    >
                      <Send className="h-4 w-4 mr-2" />
                      {isTranscribing ? "Transcribing..." : loading ? "Submitting..." : "Submit Answer"}
                    </Button>
                  </div>

                  {recordingDuration > 0 && !isRecording && (
                    <p className="text-sm text-muted-foreground">
                      ✓ Recorded {recordingDuration.toFixed(1)}s | {answer.split(' ').length} words
                    </p>
                  )}
                </Card>

                {currentFeedback && (
                  <Card className="p-6 space-y-4 bg-primary/5">
                    <h3 className="text-xl font-semibold flex items-center gap-2">
                      <CheckCircle className="h-5 w-5 text-green-600" />
                      Feedback
                    </h3>

                    <div className="flex flex-wrap items-center gap-3">
                      <Badge variant={isAnswerCorrect ? "default" : "destructive"}>
                        {isAnswerCorrect ? "Correct" : "Needs more work"}
                      </Badge>
                      {coveragePercent !== null && (
                        <span className="text-sm text-muted-foreground">
                          {coveragePercent}% key points covered
                        </span>
                      )}
                      {expectedComplexityLabel && (
                        <span className="text-xs uppercase tracking-wide text-muted-foreground">
                          Expected: {expectedComplexityLabel}
                        </span>
                      )}
                    </div>
                    
                    {/* Display the actual submitted answer */}
                    <div className="bg-background/50 p-4 rounded-lg border">
                      <p className="text-sm font-medium text-muted-foreground mb-2">Your Answer:</p>
                      <p className="text-base whitespace-pre-wrap">{currentFeedback.evaluation.answer || "No answer recorded"}</p>
                    </div>
                    
                    <div className="grid md:grid-cols-3 gap-4">
                      <div>
                        <p className="text-sm text-muted-foreground">Technical Accuracy</p>
                        <p className="text-2xl font-bold text-primary">
                          {currentFeedback.evaluation.technical_accuracy.toFixed(0)}%
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-muted-foreground">Completeness</p>
                        <p className="text-2xl font-bold text-primary">
                          {currentFeedback.evaluation.completeness.toFixed(0)}%
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-muted-foreground">Clarity</p>
                        <p className="text-2xl font-bold text-primary">
                          {currentFeedback.evaluation.clarity.toFixed(0)}%
                        </p>
                      </div>
                    </div>

                    {(matchedConcepts.length > 0 || missingConcepts.length > 0) && (
                      <div className="grid md:grid-cols-2 gap-4">
                        <div>
                          <p className="text-sm font-medium flex items-center gap-2">
                            <CheckCircle className="h-4 w-4 text-green-600" />
                            Covered Concepts
                          </p>
                          <ul className="text-sm text-muted-foreground space-y-1 mt-2">
                            {matchedConcepts.length > 0 ? (
                              matchedConcepts.map((concept: string) => (
                                <li key={concept}>{concept}</li>
                              ))
                            ) : (
                              <li className="italic">No key concepts detected</li>
                            )}
                          </ul>
                        </div>
                        <div>
                          <p className="text-sm font-medium flex items-center gap-2">
                            <AlertCircle className="h-4 w-4 text-orange-600" />
                            Missing Concepts
                          </p>
                          <ul className="text-sm text-muted-foreground space-y-1 mt-2">
                            {missingConcepts.length > 0 ? (
                              missingConcepts.map((concept: string) => (
                                <li key={concept}>{concept}</li>
                              ))
                            ) : (
                              <li className="italic">All essential concepts covered</li>
                            )}
                          </ul>
                        </div>
                      </div>
                    )}

                    {currentFeedback.evaluation.reference_answer && (
                      <div className="bg-background/50 p-4 rounded-lg border">
                        <p className="text-sm font-medium text-muted-foreground mb-2">Model Answer Snapshot:</p>
                        <p className="text-sm whitespace-pre-wrap text-muted-foreground">
                          {currentFeedback.evaluation.reference_answer}
                        </p>
                      </div>
                    )}

                    <div>
                      <p className="text-sm text-muted-foreground mb-2">Detailed Feedback:</p>
                      <p className="text-base">{currentFeedback.evaluation.feedback}</p>
                    </div>

                    {currentFeedback.evaluation.follow_up_questions && currentFeedback.evaluation.follow_up_questions.length > 0 && (
                      <div>
                        <p className="text-sm text-muted-foreground mb-2">Follow-up Questions:</p>
                        <ul className="list-disc list-inside space-y-1">
                          {currentFeedback.evaluation.follow_up_questions.map((question: string, idx: number) => (
                            <li key={idx}>{question}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {currentFeedback.speech_analysis && (
                      <div className="border-t pt-4">
                        <p className="text-sm font-medium mb-2">Speech Analysis:</p>
                        <div className="grid md:grid-cols-2 gap-3 text-sm">
                          <div>
                            <span className="text-muted-foreground">Word Count: </span>
                            <span className="font-medium">{currentFeedback.speech_analysis.word_count}</span>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Speech Rate: </span>
                            <span className="font-medium">{currentFeedback.speech_analysis.speech_rate_wpm} WPM</span>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Filler Words: </span>
                            <span className="font-medium">{currentFeedback.speech_analysis.filler_word_count}</span>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Confidence: </span>
                            <span className="font-medium">{currentFeedback.speech_analysis.confidence_score.toFixed(0)}%</span>
                          </div>
                        </div>
                        <p className="text-sm text-muted-foreground mt-2">{currentFeedback.speech_analysis.feedback}</p>
                      </div>
                    )}
                  </Card>
                )}
              </>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
