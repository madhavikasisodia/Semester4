'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/store'
import { api } from '@/lib/api'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Loader2, Upload, CheckCircle2, XCircle, FileText, TrendingUp } from 'lucide-react'

interface ResumeAnalysis {
  resume_id: number
  filename: string
  job_preference?: string
  overall_score: number
  match_percentage: number
  summary: string
  extracted_text_preview: string
  extracted_skills: string[]
  matched_skills: Array<{ skill: string; found_in_resume: boolean; importance: string }>
  missing_skills: Array<{ skill: string; found_in_resume: boolean; importance: string }>
  experience_years?: number
  recommendations: string[]
  strengths: string[]
  analyzed_at: string
}

interface Resume {
  id: number
  filename: string
  upload_date: string
  size_kb: number
  overall_score?: number
  match_percentage?: number
  extracted_skills?: string[]
  experience_years?: number
  job_preference?: string
}

export default function ResumePage() {
  const router = useRouter()
  const { user } = useAuthStore()
  const [resumes, setResumes] = useState<Resume[]>([])
  const [selectedResumeId, setSelectedResumeId] = useState<number | null>(null)
  const [analysis, setAnalysis] = useState<ResumeAnalysis | null>(null)
  const [jobPreference, setJobPreference] = useState<string>('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState<string>('')
  const [success, setSuccess] = useState<string>('')

  const jobOptions = [
    'backend',
    'frontend',
    'fullstack',
    'devops',
    'data science',
    'cloud',
  ]

  useEffect(() => {
    if (!user) {
      router.push('/login')
      return
    }
    fetchResumes()
  }, [user, router])

  const fetchResumes = async () => {
    try {
      const { data } = await api.get('/resume/list')
      setResumes(data)
      setError('')
    } catch (err) {
      setError('Failed to fetch resumes')
      console.error(err)
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) {
      const selectedFile = e.target.files[0]
      if (!selectedFile.name.endsWith('.pdf')) {
        setError('Only PDF files are supported')
        setFile(null)
        return
      }
      setFile(selectedFile)
      setError('')
    }
  }

  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file')
      return
    }

    if (!jobPreference) {
      setError('Please select a job preference')
      return
    }

    setLoading(true)
    setError('')
    setSuccess('')

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('job_preference', jobPreference)

      const { data } = await api.post('/resume/upload', formData)

      setSuccess(`Resume uploaded successfully! Score: ${data.overall_score?.toFixed(1)}%`)
      setFile(null)
      setSelectedResumeId(data.id)
      await fetchResumes()
      
      // Auto-analyze after upload
      setTimeout(() => handleAnalyze(data.id), 500)
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to upload resume'
      setError(errorMsg)
      console.error('Upload error:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleAnalyze = async (resumeId: number) => {
    setAnalyzing(true)
    setError('')

    try {
      // Find the resume to get its stored job preference if available
      const resume = resumes.find(r => r.id === resumeId)
      const jobPref = jobPreference || resume?.job_preference

      const config: any = {}
      if (jobPref) {
        config.params = { job_preference: jobPref }
      }
      const { data } = await api.post(`/resume/${resumeId}/analyze`, null, config)
      
      if (!data) {
        throw new Error('No analysis data received')
      }

      // Validate data structure
      if (!data.overall_score) {
        console.warn('Missing overall_score in response')
      }
      if (!data.strengths) {
        console.warn('Missing strengths in response, using empty array')
        data.strengths = []
      }
      if (!data.matched_skills) {
        console.warn('Missing matched_skills in response, using empty array')
        data.matched_skills = []
      }
      if (!data.missing_skills) {
        console.warn('Missing missing_skills in response, using empty array')
        data.missing_skills = []
      }
      if (!data.recommendations) {
        console.warn('Missing recommendations in response, using empty array')
        data.recommendations = []
      }
      if (!data.extracted_skills) {
        console.warn('Missing extracted_skills in response, using empty array')
        data.extracted_skills = []
      }
      
      setAnalysis(data)
      setSelectedResumeId(resumeId)
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to analyze resume'
      setError(errorMsg)
      console.error('Analysis error:', err)
    } finally {
      setAnalyzing(false)
    }
  }

  const getScoreBadgeColor = (score: number) => {
    if (score >= 80) return 'bg-emerald-500/15 text-emerald-700 border border-emerald-500/30'
    if (score >= 60) return 'bg-amber-500/15 text-amber-700 border border-amber-500/30'
    return 'bg-rose-500/15 text-rose-700 border border-rose-500/30'
  }

  return (
    <>
      <Navbar />
      <main className="pt-20 pb-12 min-h-screen bg-[radial-gradient(circle_at_top,_rgba(16,185,129,0.16),_transparent_55%),radial-gradient(circle_at_15%_40%,_rgba(14,165,233,0.12),_transparent_50%),radial-gradient(circle_at_80%_20%,_rgba(245,158,11,0.12),_transparent_45%)]">
        <div className="max-w-6xl mx-auto px-4 space-y-8">
          {/* Header */}
          <div className="rounded-3xl border border-border/60 bg-background/70 p-6 shadow-lg shadow-black/5 backdrop-blur">
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">Resume Analyzer</h1>
            <p className="text-sm text-muted-foreground mt-2">
              Upload and analyze your resume based on your job preferences.
            </p>
          </div>

        {/* Upload Section */}
        <Card className="p-6 border-border/60 bg-background/70 shadow-md shadow-black/5">
          <h2 className="text-xl font-semibold text-foreground mb-6">Upload Your Resume</h2>

          {error && (
            <Alert className="mb-4 border-red-500/30 bg-red-500/10">
              <XCircle className="h-4 w-4 text-red-500" />
              <AlertDescription className="text-red-500">{error}</AlertDescription>
            </Alert>
          )}

          {success && (
            <Alert className="mb-4 border-emerald-500/30 bg-emerald-500/10">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              <AlertDescription className="text-emerald-500">{success}</AlertDescription>
            </Alert>
          )}

          <div className="grid md:grid-cols-2 gap-6">
            {/* File Upload */}
            <div className="space-y-4">
              <div className="border-2 border-dashed border-border/70 rounded-2xl p-8 text-center hover:border-border transition bg-background/80">
                <FileText className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                <label className="cursor-pointer">
                  <p className="text-sm font-medium text-foreground mb-2">Click to select PDF resume</p>
                  <Input
                    type="file"
                    accept=".pdf"
                    onChange={handleFileChange}
                    className="hidden"
                  />
                </label>
                {file && <p className="text-sm text-emerald-500 mt-2">Selected: {file.name}</p>}
              </div>
            </div>

            {/* Job Preference */}
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-2">Job Preference</label>
                <Select value={jobPreference} onValueChange={setJobPreference}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select your target role" />
                  </SelectTrigger>
                  <SelectContent>
                    {jobOptions.map((option) => (
                      <SelectItem key={option} value={option}>
                        {option.charAt(0).toUpperCase() + option.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Button
                onClick={handleUpload}
                disabled={!file || !jobPreference || loading}
                className="w-full"
                size="lg"
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Uploading...
                  </>
                ) : (
                  <>
                    <Upload className="mr-2 h-4 w-4" />
                    Upload & Analyze
                  </>
                )}
              </Button>
            </div>
          </div>
        </Card>

        {/* Previous Resumes */}
        {resumes.length > 0 && (
          <Card className="p-6 border-border/60 bg-background/70 shadow-md shadow-black/5">
            <h2 className="text-xl font-semibold text-foreground mb-4">Previous Resumes</h2>
            <div className="space-y-2">
              {resumes.map((resume) => (
                <div
                  key={resume.id}
                  className="flex items-center justify-between p-4 rounded-xl hover:bg-foreground/5 cursor-pointer transition border border-border/60 bg-background/80"
                  onClick={() => !analyzing && handleAnalyze(resume.id)}
                  style={{ opacity: analyzing && selectedResumeId !== resume.id ? 0.6 : 1 }}
                >
                  <div className="flex-1">
                    <p className="font-medium text-foreground">{resume.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      Uploaded: {new Date(resume.upload_date).toLocaleDateString()}
                      {resume.job_preference && ` • Target: ${resume.job_preference}`}
                    </p>
                  </div>
                  {analyzing && selectedResumeId === resume.id ? (
                    <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
                  ) : (
                    resume.overall_score && (
                      <Badge className={getScoreBadgeColor(resume.overall_score)}>
                        Score: {resume.overall_score.toFixed(0)}%
                      </Badge>
                    )
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Analysis Results */}
        {analyzing && !analysis ? (
          <Card className="p-8 text-center border-border/60 bg-background/70 shadow-md shadow-black/5">
            <Loader2 className="h-12 w-12 mx-auto mb-4 text-blue-500 animate-spin" />
            <p className="text-muted-foreground">Analyzing your resume...</p>
          </Card>
        ) : analysis ? (
          <Card className="p-6 space-y-8 border-border/60 bg-background/70 shadow-md shadow-black/5">
            <div>
              <h2 className="text-2xl font-semibold text-foreground mb-6">Resume Analysis Results</h2>

              {/* Score Summary */}
              <div className="grid md:grid-cols-3 gap-4 mb-8">
                <Card className="p-4 bg-gradient-to-br from-emerald-500/10 to-emerald-500/5 border border-emerald-500/20">
                  <p className="text-sm text-muted-foreground mb-2">Overall Score</p>
                  <p className="text-3xl font-bold text-foreground">{analysis.overall_score.toFixed(1)}%</p>
                </Card>
                <Card className="p-4 bg-gradient-to-br from-sky-500/10 to-sky-500/5 border border-sky-500/20">
                  <p className="text-sm text-muted-foreground mb-2">Match with {analysis.job_preference}</p>
                  <p className="text-3xl font-bold text-foreground">{analysis.match_percentage.toFixed(0)}%</p>
                </Card>
                <Card className="p-4 bg-gradient-to-br from-amber-500/10 to-amber-500/5 border border-amber-500/20">
                  <p className="text-sm text-muted-foreground mb-2">Experience</p>
                  <p className="text-3xl font-bold text-foreground">
                    {analysis.experience_years ? `${analysis.experience_years}y` : 'N/A'}
                  </p>
                </Card>
              </div>
            </div>

            {/* Summary */}
            {analysis.summary && (
              <div className="p-4 bg-background/80 rounded-lg border border-border/60">
                <p className="text-foreground">{analysis.summary}</p>
              </div>
            )}

            {/* Strengths */}
            <div>
              <h3 className="text-lg font-semibold text-foreground mb-4 flex items-center">
                <CheckCircle2 className="mr-2 h-5 w-5 text-emerald-500" />
                Strengths
              </h3>
              {analysis.strengths && analysis.strengths.length > 0 ? (
                <ul className="space-y-3">
                  {analysis.strengths.map((strength, idx) => (
                    <li key={idx} className="text-foreground flex items-start bg-emerald-500/10 p-3 rounded-lg border border-emerald-500/20">
                      <span className="text-emerald-500 mr-3 font-bold">✓</span>
                      <span>{strength}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground italic">No strengths identified yet. Add more relevant skills to your resume.</p>
              )}
            </div>

            {/* Extracted Skills */}
            <div>
              <h3 className="text-lg font-semibold text-foreground mb-4">Extracted Skills ({analysis.extracted_skills?.length || 0})</h3>
              {analysis.extracted_skills && analysis.extracted_skills.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {analysis.extracted_skills.map((skill, idx) => (
                    <Badge key={idx} variant="secondary" className="bg-sky-500/15 text-sky-700 border border-sky-500/30">
                      {skill}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground italic">No skills detected. Make sure to include technical skills in your resume.</p>
              )}
            </div>

            {/* Matched Skills */}
            <div>
              <h3 className="text-lg font-semibold text-foreground mb-4 flex items-center">
                <CheckCircle2 className="mr-2 h-5 w-5 text-emerald-500" />
                Matched Skills ({analysis.matched_skills?.length || 0})
              </h3>
              {analysis.matched_skills && analysis.matched_skills.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {analysis.matched_skills.map((skill, idx) => (
                    <Badge
                      key={idx}
                      variant={skill.importance === 'high' ? 'default' : 'secondary'}
                      className={skill.importance === 'high' ? 'bg-emerald-600 text-white' : 'bg-emerald-500/15 text-emerald-700 border border-emerald-500/30'}
                    >
                      {skill.skill}
                      {skill.importance === 'high' && ' ★'}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground italic">No matched skills for {analysis.job_preference}. Consider adding relevant skills.</p>
              )}
            </div>

            {/* Missing Skills */}
            {analysis.missing_skills && analysis.missing_skills.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-foreground mb-4 flex items-center">
                  <XCircle className="mr-2 h-5 w-5 text-amber-500" />
                  Skills Gap ({analysis.missing_skills.length})
                </h3>
                <div className="space-y-2">
                  {analysis.missing_skills.filter((s) => s.importance === 'high').map((skill, idx) => (
                    <div key={idx} className="flex items-center justify-between p-3 bg-amber-500/10 rounded-lg border border-amber-500/30">
                      <span className="text-foreground font-medium">{skill.skill}</span>
                      <Badge variant="outline" className="border-amber-500/30 text-amber-700 bg-amber-500/10">
                        High Priority
                      </Badge>
                    </div>
                  ))}
                  {analysis.missing_skills.filter((s) => s.importance !== 'high').length > 0 && (
                    <div className="mt-3 p-3 bg-background/80 rounded-lg border border-border/60">
                      <p className="text-sm text-muted-foreground">Other useful skills: {analysis.missing_skills.filter((s) => s.importance !== 'high').map((s) => s.skill).join(', ')}</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Recommendations */}
            <div>
              <h3 className="text-lg font-semibold text-foreground mb-4 flex items-center">
                <TrendingUp className="mr-2 h-5 w-5 text-sky-500" />
                Recommendations for Improvement
              </h3>
              {analysis.recommendations && analysis.recommendations.length > 0 ? (
                <ul className="space-y-3">
                  {analysis.recommendations.map((rec, idx) => (
                    <li key={idx} className="text-foreground flex items-start bg-sky-500/10 p-3 rounded-lg border border-sky-500/20">
                      <span className="text-sky-600 mr-3 font-bold">{idx + 1}.</span>
                      <span>{rec}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground italic">Great job! No specific recommendations at this time.</p>
              )}
            </div>
          </Card>
        ) : (
          <Card className="p-8 text-center border-border/60 bg-background/70 shadow-md shadow-black/5">
            <FileText className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
            <p className="text-muted-foreground">Upload and analyze a resume to get started</p>
          </Card>
        )}
        </div>
      </main>
    </>
  )
}
