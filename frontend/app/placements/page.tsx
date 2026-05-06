"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { Navbar } from "@/components/navbar"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { placementAPI, type PlacementDrive, type PlacementOpening, type PlacementApplication } from "@/lib/api"
import { useAuthStore } from "@/lib/store"
import { Briefcase, Building2, Calendar, CheckCircle2, ClipboardList, Loader2 } from "lucide-react"

const DRIVE_STATUSES = ["Draft", "Open", "Closed"]
const OPENING_STATUSES = ["Open", "Closed"]

export default function PlacementsPage() {
  const router = useRouter()
  const { user } = useAuthStore()

  const [drives, setDrives] = useState<PlacementDrive[]>([])
  const [openings, setOpenings] = useState<PlacementOpening[]>([])
  const [applications, setApplications] = useState<PlacementApplication[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [driveForm, setDriveForm] = useState({
    company_name: "",
    title: "",
    description: "",
    start_date: "",
    end_date: "",
    status: "Open",
  })

  const [openingForm, setOpeningForm] = useState({
    drive_id: "",
    role_title: "",
    location: "",
    ctc: "",
    employment_type: "",
    openings_count: "",
    apply_by: "",
    status: "Open",
  })

  useEffect(() => {
    if (!user) {
      router.push("/login")
    }
  }, [user, router])

  const refreshData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [drivesData, openingsData, applicationsData] = await Promise.all([
        placementAPI.listDrives(),
        placementAPI.listOpenings(),
        placementAPI.listApplications(),
      ])
      setDrives(drivesData)
      setOpenings(openingsData)
      setApplications(applicationsData)
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load placement data.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (user) {
      refreshData()
    }
  }, [user])

  const openingsByDrive = useMemo(() => {
    return openings.reduce<Record<string, PlacementOpening[]>>((acc, opening) => {
      const key = opening.drive_id
      if (!acc[key]) acc[key] = []
      acc[key].push(opening)
      return acc
    }, {})
  }, [openings])

  const applicationsByOpening = useMemo(() => {
    return applications.reduce<Record<string, PlacementApplication>>((acc, app) => {
      acc[app.opening_id] = app
      return acc
    }, {})
  }, [applications])

  const handleCreateDrive = async () => {
    if (!driveForm.company_name.trim() || !driveForm.title.trim()) return
    setLoading(true)
    setError(null)
    try {
      await placementAPI.createDrive({
        company_name: driveForm.company_name.trim(),
        title: driveForm.title.trim(),
        description: driveForm.description.trim() || undefined,
        start_date: driveForm.start_date || undefined,
        end_date: driveForm.end_date || undefined,
        status: driveForm.status,
      })
      setDriveForm({
        company_name: "",
        title: "",
        description: "",
        start_date: "",
        end_date: "",
        status: "Open",
      })
      await refreshData()
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to create placement drive.")
      setLoading(false)
    }
  }

  const handleCreateOpening = async () => {
    if (!openingForm.drive_id || !openingForm.role_title.trim()) return
    setLoading(true)
    setError(null)
    try {
      await placementAPI.createOpening({
        drive_id: openingForm.drive_id,
        role_title: openingForm.role_title.trim(),
        location: openingForm.location.trim() || undefined,
        ctc: openingForm.ctc.trim() || undefined,
        employment_type: openingForm.employment_type.trim() || undefined,
        openings_count: openingForm.openings_count ? Number(openingForm.openings_count) : undefined,
        apply_by: openingForm.apply_by || undefined,
        status: openingForm.status,
      })
      setOpeningForm({
        drive_id: "",
        role_title: "",
        location: "",
        ctc: "",
        employment_type: "",
        openings_count: "",
        apply_by: "",
        status: "Open",
      })
      await refreshData()
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to create placement opening.")
      setLoading(false)
    }
  }

  const handleApply = async (openingId: string) => {
    setLoading(true)
    setError(null)
    try {
      await placementAPI.applyToOpening(openingId)
      await refreshData()
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to apply for the opening.")
      setLoading(false)
    }
  }

  return (
    <>
      <Navbar />
      <main className="pt-20 pb-12 min-h-screen">
        <div className="max-w-6xl mx-auto px-4 space-y-6">
          <div className="rounded-3xl border border-border/60 bg-background/60 p-6 shadow-lg shadow-black/5 backdrop-blur">
            <h1 className="text-3xl font-semibold tracking-tight flex items-center gap-3">
              <Briefcase className="h-7 w-7 text-emerald-500" />
              Placement Pipeline
            </h1>
            <p className="text-sm text-muted-foreground mt-2">
              Track company drives, openings, and your application status in one place.
            </p>
          </div>

          {error && (
            <Card className="p-4 border-red-500/40 bg-red-500/5 text-red-600">
              {error}
            </Card>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card className="p-5 border-border/60 bg-background/70 shadow-md shadow-black/5 lg:col-span-2">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-2">
                  <Building2 className="h-5 w-5 text-primary" />
                  <h2 className="text-lg font-semibold">Company Drives</h2>
                </div>
                <Button variant="outline" size="sm" onClick={refreshData} disabled={loading}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Refresh"}
                </Button>
              </div>

              {drives.length === 0 ? (
                <p className="text-sm text-muted-foreground">No drives created yet.</p>
              ) : (
                <div className="space-y-4">
                  {drives.map((drive) => (
                    <div key={drive.id} className="rounded-xl border border-border/60 bg-background/80 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="text-sm font-semibold text-foreground">{drive.company_name}</p>
                          <p className="text-sm text-muted-foreground">{drive.title}</p>
                        </div>
                        <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border border-emerald-500/30">
                          {drive.status}
                        </Badge>
                      </div>
                      {drive.description && (
                        <p className="text-sm text-muted-foreground mt-2">{drive.description}</p>
                      )}
                      <div className="mt-3 space-y-3">
                        {(openingsByDrive[drive.id] || []).map((opening) => {
                          const application = applicationsByOpening[opening.id]
                          const isOpen = opening.status === "Open"
                          return (
                            <div key={opening.id} className="rounded-lg border border-border/60 p-3">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div>
                                  <p className="text-sm font-medium text-foreground">{opening.role_title}</p>
                                  <p className="text-xs text-muted-foreground">
                                    {opening.location || "Location TBD"} · {opening.ctc || "CTC TBD"}
                                  </p>
                                </div>
                                <div className="flex items-center gap-2">
                                  <Badge className={isOpen ? "bg-blue-500/15 text-blue-600 dark:text-blue-300 border border-blue-500/30" : "bg-slate-500/10 text-slate-500 border border-slate-400/30"}>
                                    {opening.status}
                                  </Badge>
                                  {application ? (
                                    <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border border-emerald-500/30">
                                      {application.status}
                                    </Badge>
                                  ) : (
                                    <Button size="sm" onClick={() => handleApply(opening.id)} disabled={!isOpen || loading}>
                                      Apply
                                    </Button>
                                  )}
                                </div>
                              </div>
                              {opening.apply_by && (
                                <p className="text-xs text-muted-foreground mt-2">Apply by: {opening.apply_by}</p>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <div className="space-y-6">
              <Card className="p-5 border-border/60 bg-background/70 shadow-md shadow-black/5">
                <div className="flex items-center gap-2 mb-3">
                  <ClipboardList className="h-5 w-5 text-primary" />
                  <h3 className="text-lg font-semibold">My Applications</h3>
                </div>
                {applications.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No applications yet.</p>
                ) : (
                  <div className="space-y-3">
                    {applications.map((app) => (
                      <div key={app.id} className="rounded-lg border border-border/60 p-3">
                        <p className="text-sm font-medium text-foreground">{app.company_name}</p>
                        <p className="text-xs text-muted-foreground">{app.role_title}</p>
                        <div className="flex items-center gap-2 mt-2">
                          <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border border-emerald-500/30">
                            {app.status}
                          </Badge>
                          {app.applied_at && (
                            <span className="text-xs text-muted-foreground">Applied: {app.applied_at}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card className="p-5 border-border/60 bg-background/70 shadow-md shadow-black/5">
                <div className="flex items-center gap-2 mb-3">
                  <Calendar className="h-5 w-5 text-primary" />
                  <h3 className="text-lg font-semibold">Create Drive</h3>
                </div>
                <div className="space-y-3">
                  <Input
                    placeholder="Company name"
                    value={driveForm.company_name}
                    onChange={(e) => setDriveForm({ ...driveForm, company_name: e.target.value })}
                  />
                  <Input
                    placeholder="Drive title"
                    value={driveForm.title}
                    onChange={(e) => setDriveForm({ ...driveForm, title: e.target.value })}
                  />
                  <Textarea
                    placeholder="Drive description"
                    value={driveForm.description}
                    onChange={(e) => setDriveForm({ ...driveForm, description: e.target.value })}
                    rows={3}
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      type="date"
                      value={driveForm.start_date}
                      onChange={(e) => setDriveForm({ ...driveForm, start_date: e.target.value })}
                    />
                    <Input
                      type="date"
                      value={driveForm.end_date}
                      onChange={(e) => setDriveForm({ ...driveForm, end_date: e.target.value })}
                    />
                  </div>
                  <Select value={driveForm.status} onValueChange={(value) => setDriveForm({ ...driveForm, status: value })}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select status" />
                    </SelectTrigger>
                    <SelectContent>
                      {DRIVE_STATUSES.map((status) => (
                        <SelectItem key={status} value={status}>
                          {status}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button onClick={handleCreateDrive} disabled={loading} className="w-full gap-2">
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                    Create Drive
                  </Button>
                </div>
              </Card>

              <Card className="p-5 border-border/60 bg-background/70 shadow-md shadow-black/5">
                <div className="flex items-center gap-2 mb-3">
                  <Briefcase className="h-5 w-5 text-primary" />
                  <h3 className="text-lg font-semibold">Create Opening</h3>
                </div>
                <div className="space-y-3">
                  <Select
                    value={openingForm.drive_id}
                    onValueChange={(value) => setOpeningForm({ ...openingForm, drive_id: value })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select drive" />
                    </SelectTrigger>
                    <SelectContent>
                      {drives.map((drive) => (
                        <SelectItem key={drive.id} value={drive.id}>
                          {drive.company_name} - {drive.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    placeholder="Role title"
                    value={openingForm.role_title}
                    onChange={(e) => setOpeningForm({ ...openingForm, role_title: e.target.value })}
                  />
                  <Input
                    placeholder="Location"
                    value={openingForm.location}
                    onChange={(e) => setOpeningForm({ ...openingForm, location: e.target.value })}
                  />
                  <Input
                    placeholder="CTC"
                    value={openingForm.ctc}
                    onChange={(e) => setOpeningForm({ ...openingForm, ctc: e.target.value })}
                  />
                  <Input
                    placeholder="Employment type"
                    value={openingForm.employment_type}
                    onChange={(e) => setOpeningForm({ ...openingForm, employment_type: e.target.value })}
                  />
                  <Input
                    type="number"
                    min={1}
                    placeholder="Openings count"
                    value={openingForm.openings_count}
                    onChange={(e) => setOpeningForm({ ...openingForm, openings_count: e.target.value })}
                  />
                  <Input
                    type="date"
                    value={openingForm.apply_by}
                    onChange={(e) => setOpeningForm({ ...openingForm, apply_by: e.target.value })}
                  />
                  <Select value={openingForm.status} onValueChange={(value) => setOpeningForm({ ...openingForm, status: value })}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select status" />
                    </SelectTrigger>
                    <SelectContent>
                      {OPENING_STATUSES.map((status) => (
                        <SelectItem key={status} value={status}>
                          {status}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button onClick={handleCreateOpening} disabled={loading} className="w-full gap-2">
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                    Create Opening
                  </Button>
                </div>
              </Card>
            </div>
          </div>
        </div>
      </main>
    </>
  )
}
