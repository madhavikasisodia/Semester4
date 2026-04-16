'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/store'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Progress } from '@/components/ui/progress'
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
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const handleAnalyze = async (resumeId: number) => {
    setAnalyzing(true)
    setError('')

    try {
      const { data } = await api.post(`/resume/${resumeId}/analyze`, {}, {
        params: { job_preference: jobPreference }
      })
      setAnalysis(data)
      setSelectedResumeId(resumeId)
    } catch (err) {
      setError('Failed to analyze resume')
      console.error(err)
    } finally {
      setAnalyzing(false)
    }
  }

  const getScoreBadgeColor = (score: number) => {
    if (score >= 80) return 'bg-green-100 text-green-800'
    if (score >= 60) return 'bg-yellow-100 text-yellow-800'
    return 'bg-red-100 text-red-800'
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-slate-900 mb-2">Resume Analyzer</h1>
          <p className="text-slate-600">Upload and analyze your resume based on your job preferences</p>
        </div>

        {/* Upload Section */}
        <Card className="mb-8 p-6">
          <h2 className="text-2xl font-semibold text-slate-900 mb-6">Upload Your Resume</h2>

          {error && (
            <Alert className="mb-4 border-red-200 bg-red-50">
              <XCircle className="h-4 w-4 text-red-600" />
              <AlertDescription className="text-red-800">{error}</AlertDescription>
            </Alert>
          )}

          {success && (
            <Alert className="mb-4 border-green-200 bg-green-50">
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              <AlertDescription className="text-green-800">{success}</AlertDescription>
            </Alert>
          )}

          <div className="grid md:grid-cols-2 gap-6">
            {/* File Upload */}
            <div className="space-y-4">
              <div className="border-2 border-dashed border-slate-300 rounded-lg p-8 text-center hover:border-slate-400 transition">
                <FileText className="h-12 w-12 mx-auto mb-4 text-slate-400" />
                <label className="cursor-pointer">
                  <p className="text-sm font-medium text-slate-700 mb-2">Click to select PDF resume</p>
                  <Input
                    type="file"
                    accept=".pdf"
                    onChange={handleFileChange}
                    className="hidden"
                  />
                </label>
                {file && <p className="text-sm text-green-600 mt-2">Selected: {file.name}</p>}
              </div>
            </div>

            {/* Job Preference */}
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Job Preference</label>
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
          <Card className="mb-8 p-6">
            <h2 className="text-2xl font-semibold text-slate-900 mb-4">Previous Resumes</h2>
            <div className="space-y-2">
              {resumes.map((resume) => (
                <div
                  key={resume.id}
                  className="flex items-center justify-between p-4 rounded-lg hover:bg-slate-50 cursor-pointer transition border border-slate-200"
                  onClick={() => handleAnalyze(resume.id)}
                >
                  <div className="flex-1">
                    <p className="font-medium text-slate-900">{resume.filename}</p>
                    <p className="text-xs text-slate-500">
                      Uploaded: {new Date(resume.upload_date).toLocaleDateString()}
                    </p>
                  </div>
                  {resume.overall_score && (
                    <Badge className={getScoreBadgeColor(resume.overall_score)}>
                      Score: {resume.overall_score.toFixed(0)}%
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Analysis Results */}
        {analysis && (
          <Card className="p-6">
            <h2 className="text-2xl font-semibold text-slate-900 mb-6">Resume Analysis</h2>

            {/* Score Summary */}
            <div className="grid md:grid-cols-3 gap-4 mb-8">
              <Card className="p-4 bg-gradient-to-br from-blue-50 to-blue-100">
                <p className="text-sm text-slate-600 mb-2">Overall Score</p>
                <p className="text-3xl font-bold text-blue-900">{analysis.overall_score.toFixed(1)}%</p>
              </Card>
              <Card className="p-4 bg-gradient-to-br from-purple-50 to-purple-100">
                <p className="text-sm text-slate-600 mb-2">Match with {analysis.job_preference}</p>
                <p className="text-3xl font-bold text-purple-900">{analysis.match_percentage.toFixed(0)}%</p>
              </Card>
              <Card className="p-4 bg-gradient-to-br from-teal-50 to-teal-100">
                <p className="text-sm text-slate-600 mb-2">Experience</p>
                <p className="text-3xl font-bold text-teal-900">
                  {analysis.experience_years ? `${analysis.experience_years}y` : 'N/A'}
                </p>
              </Card>
            </div>

            {/* Strengths */}
            {analysis.strengths.length > 0 && (
              <div className="mb-8">
                <h3 className="text-lg font-semibold text-green-900 mb-3 flex items-center">
                  <CheckCircle2 className="mr-2 h-5 w-5 text-green-600" />
                  Strengths
                </h3>
                <ul className="space-y-2">
                  {analysis.strengths.map((strength, idx) => (
                    <li key={idx} className="text-slate-700 flex items-start">
                      <span className="text-green-600 mr-3">✓</span>
                      {strength}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Matched Skills */}
            {analysis.matched_skills.length > 0 && (
              <div className="mb-8">
                <h3 className="text-lg font-semibold text-slate-900 mb-3">Matched Skills ({analysis.matched_skills.length})</h3>
                <div className="flex flex-wrap gap-2">
                  {analysis.matched_skills.map((skill, idx) => (
                    <Badge
                      key={idx}
                      variant={skill.importance === 'high' ? 'default' : 'secondary'}
                      className="bg-green-100 text-green-800 hover:bg-green-200"
                    >
                      {skill.skill}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Missing Skills */}
            {analysis.missing_skills.length > 0 && (
              <div className="mb-8">
                <h3 className="text-lg font-semibold text-slate-900 mb-3">Skills Gap ({analysis.missing_skills.length})</h3>
                <div className="space-y-2">
                  {analysis.missing_skills.filter((s) => s.importance === 'high').map((skill, idx) => (
                    <div key={idx} className="flex items-center justify-between p-3 bg-red-50 rounded-lg">
                      <span className="text-slate-700">{skill.skill}</span>
                      <Badge variant="outline" className="border-red-200 text-red-700">
                        High Priority
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Recommendations */}
            {analysis.recommendations.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-slate-900 mb-3 flex items-center">
                  <TrendingUp className="mr-2 h-5 w-5 text-blue-600" />
                  Recommendations
                </h3>
                <ul className="space-y-2">
                  {analysis.recommendations.map((rec, idx) => (
                    <li key={idx} className="text-slate-700 flex items-start">
                      <span className="text-blue-600 mr-3">→</span>
                      {rec}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        )}

        {!analysis && (
          <Card className="p-8 text-center">
            <FileText className="h-12 w-12 mx-auto mb-4 text-slate-300" />
            <p className="text-slate-600">Upload and analyze a resume to get started</p>
          </Card>
        )}
      </div>
    </div>
  )
}
