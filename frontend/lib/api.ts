import axios from "axios"

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000",
})

const TOKEN_STORAGE_KEYS = ["auth_token", "token", "access_token"] as const
const USER_STORAGE_KEY = "edunerve_user"

const buildApiUrl = (path: string) => {
  const base = api.defaults.baseURL || ""
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base
  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  return `${normalizedBase}${normalizedPath}` || path
}

const persistAccessToken = (token: string) => {
  TOKEN_STORAGE_KEYS.forEach((key) => localStorage.setItem(key, token))
}

const clearStoredSession = () => {
  TOKEN_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key))
  localStorage.removeItem("refresh_token")
  localStorage.removeItem(USER_STORAGE_KEY)
}

let refreshPromise: Promise<string | null> | null = null

const refreshAuthToken = async (): Promise<string | null> => {
  if (typeof window === "undefined") return null
  const refreshToken = localStorage.getItem("refresh_token")
  if (!refreshToken) return null

  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const url = buildApiUrl("/auth/refresh")
        const { data } = await axios.post<AuthResponse>(url, { refresh_token: refreshToken })

        if (data.access_token) {
          persistAccessToken(data.access_token)
        }

        if (data.refresh_token) {
          localStorage.setItem("refresh_token", data.refresh_token)
        }

        if (data.email) {
          const fallbackName = data.email.split("@")[0] || "user"
          try {
            const rawUser = localStorage.getItem(USER_STORAGE_KEY)
            const parsedUser = rawUser ? JSON.parse(rawUser) : {}
            const updatedUser = {
              ...parsedUser,
              id: data.user_id,
              email: data.email,
              name: parsedUser?.name || fallbackName,
              role: parsedUser?.role || "student",
            }
            localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(updatedUser))
          } catch {
            localStorage.setItem(
              USER_STORAGE_KEY,
              JSON.stringify({ id: data.user_id, email: data.email, name: fallbackName, role: "student" })
            )
          }
        }

        return data.access_token ?? null
      } catch (error) {
        clearStoredSession()
        return null
      } finally {
        refreshPromise = null
      }
    })()
  }

  return refreshPromise
}


api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    
    const token =
      localStorage.getItem("auth_token") ||
      localStorage.getItem("token") ||
      localStorage.getItem("access_token")

    if (token) {
      config.headers = config.headers ?? {}
      ;(config.headers as any).Authorization = `Bearer ${token}`
    }
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status
    const originalRequest = error.config
    const isAuthRoute = typeof originalRequest?.url === "string" && originalRequest.url.includes("/auth/")

    if (
      status === 401 &&
      typeof window !== "undefined" &&
      originalRequest &&
      !isAuthRoute &&
      !(originalRequest as any)._retry
    ) {
      ;(originalRequest as any)._retry = true
      const newToken = await refreshAuthToken()
      if (newToken) {
        originalRequest.headers = originalRequest.headers ?? {}
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return api(originalRequest)
      }
    }

    return Promise.reject(error)
  }
)

// ==================== TYPE DEFINITIONS ====================

// Profile Types
export interface LeetCodeProfile {
  username: string
  ranking?: number
  total_solved?: number
  easy_solved?: number
  medium_solved?: number
  hard_solved?: number
  acceptance_rate?: number
  reputation?: number
  contribution_points?: number
}

export interface GitHubProfile {
  username: string
  name?: string
  bio?: string
  public_repos?: number
  followers?: number
  following?: number
  avatar_url?: string
  html_url?: string
  created_at?: string
  location?: string
  blog?: string
}

export interface CodeChefProfile {
  username: string
  rating?: number
  stars?: string
  highest_rating?: number
  highest_rating_time?: string | null
  global_rank?: number
  country_rank?: number
  fully_solved?: number
  partially_solved?: number
}

export interface CombinedProfile {
  leetcode: LeetCodeProfile
  github: GitHubProfile
}

export interface AuthResponse {
  user_id: string
  email: string
  message: string
  access_token?: string
  refresh_token?: string
}

export interface LoginPayload {
  email: string
  password: string
}

export interface SignupPayload extends LoginPayload {
  metadata?: Record<string, any>
}

// Learning Management Types
export interface Resource {
  title: string
  url: string
}

export interface Recommendation {
  id: number
  user_id: number
  title: string
  description: string
  category: string
  priority: string
  source: string
  resources: Resource[]
  estimated_time: string
  status: string
  created_at: string
  completed_at?: string
}

export interface TopicResource {
  title: string
  url: string
  source: string
  content_type: string
  summary?: string
}

export interface TopicResourceResponse {
  topic: string
  items: TopicResource[]
  fetched_at: string
}

export interface ProgressStats {
  total_problems_solved: number
  total_tests_taken: number
  total_interviews: number
  current_streak: number
  longest_streak: number
  total_time_spent_hours: number
  achievements_earned: number
  avg_test_score: number
}

export interface ProgressHistory {
  id: number
  user_id: number
  date: string
  problems_solved: number
  tests_taken: number
  interviews_completed: number
  time_spent_minutes: number
  skills_practiced: string[]
  current_streak: number
  longest_streak: number
}

export interface Achievement {
  id: number
  user_id: number
  title: string
  description: string
  badge_icon: string
  earned_date: string
  category: string
  points: number
}

export interface TestScore {
  id: number
  user_id: number
  test_type: string
  subject: string
  score: number
  max_score: number
  percentage: number
  date_taken: string
  duration_minutes: number
  topics_covered: string[]
  weak_topics: string[]
}

// Question Types
export interface Question {
  id: string
  title: string
  difficulty: string
  description: string
  link: string
  source: string
  tags?: string[]
  companies?: string[]
}

// Company Types
export interface Company {
  name: string
  description: string
  headquarters: string
  industry: string
  founded: number
  employees: string
  website: string
}

export interface CompanyRequirements {
  company: string
  technical_skills: string[]
  soft_skills: string[]
  educational_requirements: string[]
  experience_levels: {
    entry: string
    mid: string
    senior: string
  }
  certifications: string[]
}

export interface HiringProcess {
  company: string
  stages: Array<{
    stage_number: number
    name: string
    description: string
    duration: string
    tips: string[]
  }>
  total_duration: string
  preparation_tips: string[]
}

export interface SalaryInfo {
  company: string
  positions: Array<{
    role: string
    level: string
    salary_range: string
    stock_options: string
    bonus: string
    benefits: string[]
  }>
  location_factor: string
  negotiation_tips: string[]
}

export interface PreparationGuide {
  company: string
  technical_preparation: {
    data_structures: string[]
    algorithms: string[]
    system_design_topics: string[]
    coding_practice_sites: string[]
  }
  behavioral_preparation: {
    common_questions: string[]
    tips: string[]
  }
  resources: {
    books: string[]
    online_courses: string[]
    practice_platforms: string[]
  }
  timeline: string
}

// AI Interview Types
export interface Persona {
  persona_id: string
  name: string
  tone: string
  style: string
  intro_message: string
  
  // Mapped fields for UI compatibility
  id?: string
  description?: string
  focus_areas?: string[]
  communication_style?: string
  difficulty_preference?: string
}

export interface InterviewSession {
  session_id: string
  persona: string
  question_count: number
  current_question_number: number
  current_question: string
  current_question_text?: string
  current_question_id?: string
  current_question_difficulty?: string
  total_questions?: number
  difficulty: string
  start_time: string
  interviewer?: {
    id?: string
    name?: string
    tone?: string
    style?: string
    intro_message?: string
  }
}

export interface AnswerResponse {
  evaluation: {
    question: string
    answer: string
    technical_accuracy: number
    completeness: number
    clarity: number
    has_real_world_examples: boolean
    has_structured_approach: boolean
    feedback: string
    follow_up_questions: string[]
    matched_concepts?: string[]
    missing_concepts?: string[]
    coverage_ratio?: number
    is_correct?: boolean
    reference_answer?: string | null
    expected_complexity?: {
      time?: string
      space?: string
      [key: string]: string | undefined
    } | null
  }
  question_number: number
  total_questions_asked: number
  speech_analysis?: {
    filler_word_count: number
    filler_words: string[]
    word_count: number
    speech_rate_wpm: number
    confidence_score: number
    feedback: string
  }
  next_question?: {
    question_id: string
    question: string
    difficulty: string
    question_text?: string
  }
  status: "continue" | "active" | "completed"
  message?: string
}

export interface InterviewReport {
  session_id: string
  candidate_name: string
  target_role: string
  interview_type: string
  persona_used: string
  duration_minutes: number
  
  // Overall Scores
  overall_score: number
  technical_score: number
  communication_score: number
  confidence_score: number
  body_language_score: number
  
  // Detailed Analysis
  total_questions: number
  questions_answered: number
  correct_answers?: number
  average_response_time: number
  
  // Speech Analytics
  total_filler_words: number
  speech_clarity: number
  average_speech_rate: number
  
  // Strengths & Weaknesses
  strengths: string[]
  weaknesses: string[]
  improvement_areas: string[]
  
  // Question-wise Performance
  question_performance: Array<{
    question_number: number
    question: string
    difficulty: string
    score: number
    feedback: string
    is_correct?: boolean
    missing_concepts?: string[]
  }>
  
  // Recommendations
  recommended_topics: string[]
  recommended_practice: string[]
  
  // AI Feedback
  detailed_feedback: string
  confidence_trend: string
  final_verdict: string
  
  // Legacy fields for compatibility
  average_confidence?: number
  areas_for_improvement?: string[]
  improvements?: string[]
  recommendations?: string[]
  performance_breakdown?: any
}

// ==================== AUTH API ====================

export const authAPI = {
  async login(payload: LoginPayload): Promise<AuthResponse> {
    const { data } = await api.post("/auth/login", payload)
    return data
  },

  async signup(payload: SignupPayload): Promise<AuthResponse> {
    const { data } = await api.post("/auth/signup", payload)
    return data
  },
}

// ==================== PROFILE API ====================

export const profileAPI = {
  // Get LeetCode profile
  async getLeetCodeProfile(username: string): Promise<LeetCodeProfile> {
    const { data } = await api.get(`/leetcode/${username}`)
    return data
  },

  // Get GitHub profile
  async getGitHubProfile(username: string): Promise<GitHubProfile> {
    const { data } = await api.get(`/github/${username}`)
    return data
  },

  // Get combined profile
  async getCombinedProfile(
    leetcodeUsername: string,
    githubUsername: string
  ): Promise<CombinedProfile> {
    const { data } = await api.get(`/profile/${leetcodeUsername}/${githubUsername}`)
    return data
  },

  // Get CodeChef profile
  async getCodeChefProfile(username: string): Promise<CodeChefProfile> {
    const { data } = await api.get(`/codechef/${username}`)
    return data
  },
}

// ==================== QUESTIONS API ====================

export const questionsAPI = {
  // Get all available subjects
  async getSubjects(): Promise<string[]> {
    const { data } = await api.get("/questions/subjects")
    return data.subjects
  },

  // Get questions by subject
  async getQuestionsBySubject(
    subject: string,
    difficulty?: string,
    source?: string,
    limit?: number
  ): Promise<Question[]> {
    const params = new URLSearchParams()
    if (difficulty) params.append("difficulty", difficulty)
    if (source) params.append("source", source)
    if (limit) params.append("limit", limit.toString())

    const { data } = await api.get(`/questions/${subject}?${params.toString()}`)
    return data.questions
  },

  // Search questions
  async searchQuestions(
    query: string,
    subject?: string,
    difficulty?: string
  ): Promise<Question[]> {
    const params = new URLSearchParams({ query })
    if (subject) params.append("subject", subject)
    if (difficulty) params.append("difficulty", difficulty)

    const { data } = await api.get(`/questions/search?${params.toString()}`)
    return data.questions
  },

  // Get random questions
  async getRandomQuestions(count: number = 5, difficulty?: string): Promise<Question[]> {
    const params = new URLSearchParams({ count: count.toString() })
    if (difficulty) params.append("difficulty", difficulty)

    const { data } = await api.get(`/questions/random?${params.toString()}`)
    return data.questions
  },
}

// ==================== COMPANIES API ====================

export const companiesAPI = {
  // Get all companies
  async getAllCompanies(): Promise<Company[]> {
    const { data } = await api.get("/companies/list")
    return data.companies
  },

  // Get company details
  async getCompanyDetails(companyName: string): Promise<Company> {
    const { data } = await api.get(`/companies/${companyName}`)
    return data
  },

  // Get company requirements
  async getCompanyRequirements(companyName: string): Promise<CompanyRequirements> {
    const { data } = await api.get(`/companies/${companyName}/requirements`)
    return data
  },

  // Get hiring process
  async getHiringProcess(companyName: string): Promise<HiringProcess> {
    const { data } = await api.get(`/companies/${companyName}/process`)
    return data
  },

  // Get salary information
  async getSalaryInfo(companyName: string): Promise<SalaryInfo> {
    const { data } = await api.get(`/companies/${companyName}/salary`)
    return data
  },

  // Get preparation guide
  async getPreparationGuide(companyName: string): Promise<PreparationGuide> {
    const { data } = await api.get(`/companies/${companyName}/preparation`)
    return data
  },

  // Search companies
  async searchCompanies(query: string): Promise<Company[]> {
    const { data } = await api.get(`/companies/search?query=${query}`)
    return data.companies
  },
}

// ==================== LEARNING MANAGEMENT API ====================

export const learningAPI = {
  // Get personalized recommendations
  async getRecommendations(status?: string, priority?: string): Promise<Recommendation[]> {
    const params = new URLSearchParams()
    if (status) params.append("status", status)
    if (priority) params.append("priority", priority)
    
    const query = params.toString()
    const url = query ? `/recommendations?${query}` : "/recommendations"
    const { data } = await api.get(url)
    return data
  },

  async getTopicResources(topic: string): Promise<TopicResourceResponse> {
    const safeTopic = encodeURIComponent(topic)
    const { data } = await api.get(`/topics/${safeTopic}/resources`)
    return data
  },

  // Generate new recommendations based on user data
  async generateRecommendations(): Promise<{ message: string }> {
    const { data } = await api.post("/recommendations/generate")
    return data
  },

  // Update recommendation status
  async updateRecommendationStatus(recId: number, status: string): Promise<{ message: string }> {
    const { data } = await api.put(`/recommendations/${recId}/status?status=${status}`)
    return data
  },

  // Get progress statistics
  async getProgressStats(): Promise<ProgressStats> {
    const { data } = await api.get("/progress/stats")
    return data
  },

  // Get progress history
  async getProgressHistory(days: number = 30): Promise<ProgressHistory[]> {
    const { data } = await api.get(`/progress/history?days=${days}`)
    return data
  },

  // Get achievements
  async getAchievements(): Promise<Achievement[]> {
    const { data } = await api.get("/achievements")
    return data
  },

  // Get dashboard overview
  async getDashboardOverview(): Promise<{
    resumes: any[]
    test_scores: TestScore[]
    certifications: any[]
    recommendations: Recommendation[]
    progress_stats: ProgressStats
  }> {
    const { data } = await api.get("/dashboard/overview")
    return data
  },
}

// ==================== RESUME & CERTIFICATE API ====================

export const resumeAPI = {
  // Upload resume
  async uploadResume(file: File): Promise<{
    id: number
    filename: string
    upload_date: string
    message: string
  }> {
    const formData = new FormData()
    formData.append("file", file)
    
    const { data } = await api.post("/resume/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    })
    return data
  },

  // Analyze resume
  async analyzeResume(resumeId: number): Promise<any> {
    const { data } = await api.post(`/resume/${resumeId}/analyze`)
    return data
  },

  // List resumes
  async listResumes(): Promise<any[]> {
    const { data } = await api.get("/resume/list")
    return data
  },
}

export const certificateAPI = {
  // Upload certificate
  async uploadCertificate(
    file: File,
    name: string,
    issuingOrganization: string,
    issueDate: string,
    credentialId?: string,
    credentialUrl?: string,
    expiryDate?: string
  ): Promise<{
    id: number
    name: string
    message: string
  }> {
    const formData = new FormData()
    formData.append("file", file)
    
    // Send individual form fields that FastAPI can parse as CertificationCreate
    formData.append("name", name)
    formData.append("issuing_organization", issuingOrganization)
    formData.append("issue_date", issueDate)
    
    if (credentialId) formData.append("credential_id", credentialId)
    if (credentialUrl) formData.append("credential_url", credentialUrl)
    if (expiryDate) formData.append("expiry_date", expiryDate)
    
    const { data } = await api.post("/certifications", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    })
    return { ...data, message: "Certificate uploaded successfully" }
  },

  // List certificates
  async listCertificates(): Promise<any[]> {
    const { data } = await api.get("/certifications")
    return data
  },
}

// ==================== AI INTERVIEW API ====================

export const interviewAPI = {
  // Get all available personas
  async getPersonas(): Promise<Persona[]> {
    const { data } = await api.get("/interview/personas")
    // Map backend response to frontend interface
    return data.personas.map((p: any) => ({
      ...p,
      id: p.persona_id, // Map persona_id to id for UI compatibility
      description: p.style, // Use style as description
      communication_style: p.tone,
      focus_areas: [] // Not provided by backend
    }))
  },

  // Start a new interview session
  async startInterview(
    persona: string,
    candidateName: string,
    targetRole: string,
    interviewType: string = "technical",
    difficulty: string = "medium",
    durationMinutes: number = 30,
    companyContext?: string
  ): Promise<InterviewSession> {
    const { data } = await api.post("/interview/start", {
      persona,
      interview_type: interviewType,
      difficulty,
      duration_minutes: durationMinutes,
      candidate_name: candidateName,
      target_role: targetRole,
      company_context: companyContext,
    })
    return data
  },

  // Submit an answer
  async submitAnswer(
    sessionId: string, 
    answer: string,
    audioDuration?: number
  ): Promise<AnswerResponse> {
    const params = new URLSearchParams()
    params.append("answer", answer)
    if (audioDuration) {
      params.append("audio_duration", audioDuration.toString())
    }
    
    const { data } = await api.post(
      `/interview/${sessionId}/answer?${params.toString()}`
    )
    return data
  },

  // Get interview status
  async getInterviewStatus(sessionId: string): Promise<{
    session_id: string
    status: string
    candidate_name: string
    target_role: string
    interview_type: string
    persona: string
    questions_asked: number
    questions_answered: number
    current_question_index: number
    start_time: string
    end_time: string | null
  }> {
    const { data } = await api.get(`/interview/${sessionId}/status`)
    return data
  },

  // Get interview report
  async getInterviewReport(sessionId: string): Promise<InterviewReport> {
    const { data } = await api.get(`/interview/${sessionId}/report`)
    return data
  },

  // Delete interview session
  async deleteInterview(sessionId: string): Promise<{ message: string }> {
    const { data } = await api.delete(`/interview/${sessionId}`)
    return data
  },

  // Get active sessions
  async getActiveSessions(): Promise<{
    total_sessions: number
    sessions: Array<{
      session_id: string
      candidate_name: string
      target_role: string
      status: string
      questions_answered: number
      start_time: string
    }>
  }> {
    const { data } = await api.get("/interview/sessions/active")
    return data
  },

  // Analyze speech only
  async analyzeSpeech(
    text: string,
    durationSeconds: number
  ): Promise<{
    speech_analysis: {
      word_count: number
      filler_word_count: number
      filler_words_found: string[]
      speech_rate_wpm: number
      pause_count: number
      confidence_score: number
    }
    recommendations: string[]
    overall_rating: string
  }> {
    const params = new URLSearchParams()
    params.append("text", text)
    params.append("duration_seconds", durationSeconds.toString())
    
    const { data } = await api.post(
      `/interview/analyze-speech?${params.toString()}`
    )
    return data
  },
}

// ==================== HEALTH CHECK ====================

export const healthAPI = {
  async checkHealth(): Promise<{ status: string; timestamp: string }> {
    const { data } = await api.get("/health")
    return data
  },
}
