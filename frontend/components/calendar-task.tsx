"use client"

import { useState, useEffect, useCallback } from "react"
import { Calendar } from "@/components/ui/calendar"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Spinner } from "@/components/ui/spinner"
import { AlertCircle, Calendar as CalendarIcon, CheckCircle2, Clock, Trash2, Edit2, Plus } from "lucide-react"
import { format, isToday, isBefore, startOfDay } from "date-fns"
import { useAuthStore } from "@/lib/store"

interface Task {
  id: string
  title: string
  description?: string
  dueDate: Date
  readinessLevel?: number // 1-5 scale
  feedback?: string
  isCompleted?: boolean
  createdAt: Date
}

interface ReadinessResponse {
  taskId: string
  readinessLevel: number
  feedback: string
  responseDate: Date
}

const READINESS_LEVELS = [
  { value: 1, label: "Not Ready", color: "bg-red-100 text-red-800" },
  { value: 2, label: "Somewhat Ready", color: "bg-orange-100 text-orange-800" },
  { value: 3, label: "Moderately Ready", color: "bg-yellow-100 text-yellow-800" },
  { value: 4, label: "Mostly Ready", color: "bg-lime-100 text-lime-800" },
  { value: 5, label: "Very Ready", color: "bg-green-100 text-green-800" },
]

const STORAGE_KEY = "calendar_tasks"
const RESPONSES_KEY = "readiness_responses"

export function CalendarTask() {
  const { user } = useAuthStore()
  const [tasks, setTasks] = useState<Task[]>([])
  const [selectedDate, setSelectedDate] = useState<Date>(new Date())
  const [showTaskForm, setShowTaskForm] = useState(false)
  const [showReadinessDialog, setShowReadinessDialog] = useState(false)
  const [editingTask, setEditingTask] = useState<Task | null>(null)
  const [formData, setFormData] = useState({ title: "", description: "" })
  const [readinessData, setReadinessData] = useState({ level: 3, feedback: "" })
  const [selectedTaskForReadiness, setSelectedTaskForReadiness] = useState<Task | null>(null)
  const [responses, setResponses] = useState<ReadinessResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [successMessage, setSuccessMessage] = useState("")

  // Load tasks and responses from localStorage
  useEffect(() => {
    try {
      const storedTasks = localStorage.getItem(`${STORAGE_KEY}_${user?.id}`)
      const storedResponses = localStorage.getItem(`${RESPONSES_KEY}_${user?.id}`)

      if (storedTasks) {
        const parsed = JSON.parse(storedTasks) as Task[]
        setTasks(
          parsed.map((t) => ({
            ...t,
            dueDate: new Date(t.dueDate),
            createdAt: new Date(t.createdAt),
          }))
        )
      }

      if (storedResponses) {
        const parsed = JSON.parse(storedResponses) as ReadinessResponse[]
        setResponses(
          parsed.map((r) => ({
            ...r,
            responseDate: new Date(r.responseDate),
          }))
        )
      }
    } catch (error) {
      console.error("Failed to load tasks from storage:", error)
    }
  }, [user?.id])

  // Check for tasks due today
  useEffect(() => {
    const today = startOfDay(new Date())
    const tasksDueToday = tasks.filter(
      (task) =>
        startOfDay(task.dueDate).getTime() === today.getTime() &&
        !task.isCompleted &&
        !responses.some((r) => r.taskId === task.id)
    )

    if (tasksDueToday.length > 0) {
      // Auto-open readiness dialog for the first due task
      setSelectedTaskForReadiness(tasksDueToday[0])
      setShowReadinessDialog(true)
    }
  }, [tasks, responses])

  const saveTasks = useCallback(
    (updatedTasks: Task[]) => {
      if (!user?.id) return
      localStorage.setItem(
        `${STORAGE_KEY}_${user.id}`,
        JSON.stringify(updatedTasks)
      )
      setTasks(updatedTasks)
    },
    [user?.id]
  )

  const saveResponses = useCallback(
    (updatedResponses: ReadinessResponse[]) => {
      if (!user?.id) return
      localStorage.setItem(
        `${RESPONSES_KEY}_${user.id}`,
        JSON.stringify(updatedResponses)
      )
      setResponses(updatedResponses)
    },
    [user?.id]
  )

  const handleAddTask = () => {
    if (!formData.title.trim()) return

    const newTask: Task = {
      id: Math.random().toString(36).substr(2, 9),
      title: formData.title,
      description: formData.description || undefined,
      dueDate: selectedDate,
      createdAt: new Date(),
      isCompleted: false,
    }

    const updatedTasks = [...tasks, newTask]
    saveTasks(updatedTasks)

    setFormData({ title: "", description: "" })
    setShowTaskForm(false)
    setEditingTask(null)
    setSuccessMessage("Task created successfully!")
    setTimeout(() => setSuccessMessage(""), 3000)
  }

  const handleUpdateTask = () => {
    if (!editingTask || !formData.title.trim()) return

    const updatedTasks = tasks.map((t) =>
      t.id === editingTask.id
        ? {
            ...t,
            title: formData.title,
            description: formData.description || undefined,
            dueDate: selectedDate,
          }
        : t
    )

    saveTasks(updatedTasks)

    setFormData({ title: "", description: "" })
    setShowTaskForm(false)
    setEditingTask(null)
    setSuccessMessage("Task updated successfully!")
    setTimeout(() => setSuccessMessage(""), 3000)
  }

  const handleDeleteTask = (taskId: string) => {
    const updatedTasks = tasks.filter((t) => t.id !== taskId)
    saveTasks(updatedTasks)
    setSuccessMessage("Task deleted successfully!")
    setTimeout(() => setSuccessMessage(""), 3000)
  }

  const handleEditTask = (task: Task) => {
    setEditingTask(task)
    setSelectedDate(task.dueDate)
    setFormData({ title: task.title, description: task.description || "" })
    setShowTaskForm(true)
  }

  const handleSubmitReadiness = async () => {
    if (!selectedTaskForReadiness) return

    setLoading(true)

    try {
      // Simulate API call - replace with actual API call if backend is available
      await new Promise((resolve) => setTimeout(resolve, 500))

      const newResponse: ReadinessResponse = {
        taskId: selectedTaskForReadiness.id,
        readinessLevel: readinessData.level,
        feedback: readinessData.feedback,
        responseDate: new Date(),
      }

      const updatedResponses = [...responses, newResponse]
      saveResponses(updatedResponses)

      // Mark task as completed
      const updatedTasks = tasks.map((t) =>
        t.id === selectedTaskForReadiness.id
          ? { ...t, isCompleted: true, readinessLevel: readinessData.level, feedback: readinessData.feedback }
          : t
      )
      saveTasks(updatedTasks)

      setSuccessMessage(
        `Readiness response saved! You rated your readiness as "${READINESS_LEVELS[readinessData.level - 1].label}"`
      )

      setTimeout(() => {
        setShowReadinessDialog(false)
        setReadinessData({ level: 3, feedback: "" })
        setSelectedTaskForReadiness(null)
        setSuccessMessage("")
      }, 2000)
    } catch (error) {
      console.error("Failed to save readiness response:", error)
      setSuccessMessage("Failed to save response. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  const tasksForSelectedDate = tasks.filter(
    (task) => startOfDay(task.dueDate).getTime() === startOfDay(selectedDate).getTime()
  )

  const tasksWithResponses = tasks.filter((task) =>
    responses.some((r) => r.taskId === task.id)
  )

  const datesWithTasks = Array.from(
    new Set(tasks.map((t) => format(t.dueDate, "yyyy-MM-dd")))
  )

  return (
    <div className="space-y-6">
      {successMessage && (
        <Alert className="bg-green-50 border-green-200">
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          <AlertDescription className="text-green-800">{successMessage}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Calendar Section */}
        <div className="lg:col-span-1">
          <Card className="p-4">
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <CalendarIcon className="h-5 w-5" />
              Task Calendar
            </h3>
            <Calendar
              mode="single"
              selected={selectedDate}
              onSelect={(date) => date && setSelectedDate(date)}
              disabled={(date) => isBefore(date, startOfDay(new Date())) && !isToday(date)}
              className="rounded-lg border"
            />
            <div className="mt-4 space-y-2 text-sm">
              <p className="text-xs text-gray-600">
                📌 {tasks.length} total task{tasks.length !== 1 ? "s" : ""}
              </p>
              <p className="text-xs text-gray-600">
                ✓ {tasksWithResponses.length} task{tasksWithResponses.length !== 1 ? "s" : ""} tracked
              </p>
            </div>
          </Card>
        </div>

        {/* Tasks Section */}
        <div className="lg:col-span-2 space-y-4">
          {/* Add Task Form */}
          {!showTaskForm ? (
            <Button onClick={() => setShowTaskForm(true)} className="w-full gap-2">
              <Plus className="h-4 w-4" />
              Add New Task
            </Button>
          ) : (
            <Card className="p-4">
              <h3 className="font-semibold mb-4">
                {editingTask ? "Edit Task" : "Create New Task"}
              </h3>
              <div className="space-y-4">
                <div>
                  <label className="text-sm font-medium">Task Title *</label>
                  <Input
                    placeholder="e.g., System Design Interview Prep"
                    value={formData.title}
                    onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                    className="mt-1"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">Description</label>
                  <Textarea
                    placeholder="Add any details about this task..."
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    className="mt-1"
                    rows={3}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">Due Date</label>
                  <p className="text-sm text-gray-600 mt-1">
                    Selected: <strong>{format(selectedDate, "PPP")}</strong>
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    onClick={editingTask ? handleUpdateTask : handleAddTask}
                    disabled={!formData.title.trim()}
                    className="flex-1"
                  >
                    {editingTask ? "Update Task" : "Create Task"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowTaskForm(false)
                      setEditingTask(null)
                      setFormData({ title: "", description: "" })
                    }}
                    className="flex-1"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            </Card>
          )}

          {/* Tasks for Selected Date */}
          <div>
            <h3 className="font-semibold mb-3">
              Tasks for {format(selectedDate, "PPP")}
            </h3>
            {tasksForSelectedDate.length === 0 ? (
              <Card className="p-6 text-center text-gray-500">
                <Clock className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>No tasks scheduled for this date</p>
              </Card>
            ) : (
              <div className="space-y-3">
                {tasksForSelectedDate.map((task) => {
                  const response = responses.find((r) => r.taskId === task.id)
                  return (
                    <Card key={task.id} className="p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <h4 className="font-semibold">{task.title}</h4>
                            {task.isCompleted && (
                              <Badge className="bg-green-100 text-green-800">Completed</Badge>
                            )}
                            {isToday(task.dueDate) && (
                              <Badge className="bg-blue-100 text-blue-800">Due Today</Badge>
                            )}
                          </div>
                          {task.description && (
                            <p className="text-sm text-gray-600 mb-2">{task.description}</p>
                          )}
                          {response && (
                            <div className="mt-2 p-2 bg-gray-50 rounded text-sm">
                              <p className="font-medium mb-1">
                                Readiness:{" "}
                                <span
                                  className={`px-2 py-1 rounded ${
                                    READINESS_LEVELS[response.readinessLevel - 1].color
                                  }`}
                                >
                                  {READINESS_LEVELS[response.readinessLevel - 1].label}
                                </span>
                              </p>
                              {response.feedback && (
                                <p className="text-gray-700">Feedback: {response.feedback}</p>
                              )}
                              <p className="text-xs text-gray-500 mt-1">
                                Responded: {format(response.responseDate, "PPpp")}
                              </p>
                            </div>
                          )}
                        </div>
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleEditTask(task)}
                            disabled={task.isCompleted}
                          >
                            <Edit2 className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteTask(task.id)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    </Card>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Readiness Dialog */}
      <Dialog open={showReadinessDialog} onOpenChange={setShowReadinessDialog}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-blue-600" />
              Task Readiness Assessment
            </DialogTitle>
            <DialogDescription>
              {selectedTaskForReadiness && (
                <span>
                  Today is the due date for: <strong>{selectedTaskForReadiness.title}</strong>
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          {selectedTaskForReadiness && (
            <div className="space-y-6 py-4">
              <div>
                <p className="text-sm font-semibold mb-3">
                  How ready are you for <span className="text-blue-600">{selectedTaskForReadiness.title}</span>?
                </p>
                <div className="space-y-2">
                  {READINESS_LEVELS.map((level) => (
                    <button
                      key={level.value}
                      onClick={() => setReadinessData({ ...readinessData, level: level.value })}
                      className={`w-full p-3 text-left rounded-lg border-2 transition ${
                        readinessData.level === level.value
                          ? `border-blue-500 ${level.color}`
                          : "border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      <p className="font-medium">{level.label}</p>
                      <p className="text-xs text-gray-600">
                        {level.value === 1 && "Need more preparation"}
                        {level.value === 2 && "Need some more preparation"}
                        {level.value === 3 && "Somewhat prepared"}
                        {level.value === 4 && "Well prepared"}
                        {level.value === 5 && "Fully prepared and confident"}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-sm font-medium">
                  Feedback (optional)
                </label>
                <Textarea
                  placeholder="Share your experience, concerns, or what you learned while preparing..."
                  value={readinessData.feedback}
                  onChange={(e) =>
                    setReadinessData({ ...readinessData, feedback: e.target.value })
                  }
                  className="mt-2"
                  rows={4}
                />
              </div>

              <div className="flex gap-2">
                <Button
                  onClick={handleSubmitReadiness}
                  disabled={loading}
                  className="flex-1"
                >
                  {loading ? (
                    <Spinner className="h-4 w-4" />
                  ) : (
                    <>
                      <CheckCircle2 className="h-4 w-4 mr-2" />
                      Submit Readiness
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setShowReadinessDialog(false)}
                  className="flex-1"
                  disabled={loading}
                >
                  Remind Later
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Progress Tracking Section */}
      {tasksWithResponses.length > 0 && (
        <Card className="p-6">
          <h3 className="font-semibold mb-4">📊 Progress Tracking</h3>
          <div className="space-y-3">
            {tasksWithResponses.map((task) => {
              const response = responses.find((r) => r.taskId === task.id)
              if (!response) return null
              return (
                <div
                  key={task.id}
                  className="flex items-center justify-between p-3 bg-gray-50 rounded"
                >
                  <div>
                    <p className="font-medium">{task.title}</p>
                    <p className="text-xs text-gray-600">
                      Due: {format(task.dueDate, "PPP")}
                    </p>
                  </div>
                  <div className="text-right">
                    <Badge className={READINESS_LEVELS[response.readinessLevel - 1].color}>
                      {READINESS_LEVELS[response.readinessLevel - 1].label}
                    </Badge>
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </div>
  )
}
