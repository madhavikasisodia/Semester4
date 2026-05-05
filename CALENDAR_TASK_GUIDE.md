# Calendar Task Component - User Guide

## Overview

The Calendar Task Component is a comprehensive task management and readiness tracking system for interview preparation. Users can:

- 📅 Create tasks with due dates
- ⏰ Track scheduled events on a calendar
- 🤔 Submit readiness assessments on task due dates
- 📊 View progress tracking and feedback history
- 💾 Persist all data for future reference

## Features

### 1. Task Creation
- **Add New Tasks**: Click "Add New Task" to create a new task
- **Set Due Date**: Select any date on the calendar for your task's due date
- **Add Description**: Optionally add details about the task (preparation goals, focus areas, etc.)
- **Examples of Tasks**:
  - System Design Interview Prep
  - LeetCode Practice Session
  - Behavioral Interview Practice
  - Company Research (Google, Microsoft, etc.)

### 2. Calendar View
- **Visual Overview**: See all your tasks plotted on the calendar
- **Task Counter**: Quick stats showing total tasks and tracked tasks
- **Date Selection**: Click on any date to view or add tasks for that day
- **Past Date Protection**: Cannot create tasks in the past

### 3. Readiness Assessment
When the due date arrives, an automatic dialog appears asking:

**"How ready are you for [task name]?"**

Readiness Levels:
- **1 - Not Ready** (🔴): Need more preparation
- **2 - Somewhat Ready** (🟠): Need some more preparation
- **3 - Moderately Ready** (🟡): Somewhat prepared
- **4 - Mostly Ready** (🟢): Well prepared
- **5 - Very Ready** (✅): Fully prepared and confident

### 4. Feedback Collection
- **Optional Feedback Field**: Share your experience, concerns, or what you learned
- **Examples of Useful Feedback**:
  - "Struggled with the time complexity discussion"
  - "Successfully explained the data structures"
  - "Need more practice with system design trade-offs"
  - "Feeling confident about this topic now"

### 5. Progress Tracking
- **Readiness History**: View all submitted readiness responses
- **Historical Data**: Track how your confidence levels change over time
- **Pattern Recognition**: Identify areas where you consistently feel less ready

## How It Works

### Data Storage
All data is stored in your browser's localStorage, organized by user ID. This means:
- ✅ Data persists between sessions
- ✅ Private to your device
- ⚠️ Clear browser data will delete tasks (consider exporting first)

### Future Enhancement (Backend Integration)
The component is designed to work with the backend API for persistent cloud storage:
- `POST /tasks` - Create a new task
- `GET /tasks` - Retrieve all tasks
- `PUT /tasks/{id}` - Update a task
- `DELETE /tasks/{id}` - Delete a task
- `POST /tasks/{id}/readiness` - Submit readiness response
- `GET /readiness` - Get all readiness responses
- `GET /tasks/due-today` - Get today's tasks

## Usage Workflow

### Step 1: Plan Your Prep
1. Navigate to the Calendar Task page
2. Click on future dates and add tasks
3. Include specific interview preparation goals in descriptions

### Step 2: Schedule Tasks
- Space out tasks strategically
- Balance different topics (DSA, System Design, Behavioral)
- Account for preparation time before each assessment

### Step 3: Day of Task
- When the due date arrives, the readiness dialog auto-opens
- Answer honestly - this data helps identify weak areas
- Add detailed feedback about your preparation experience

### Step 4: Review Progress
- Check the "Progress Tracking" section for historical data
- Identify patterns in your readiness levels
- Adjust future preparation strategies based on insights

## Example: Interview Prep Timeline

```
Week 1:
└─ 2025-05-12: LeetCode Arrays & Hashing (5 problems)
└─ 2025-05-15: System Design - URL Shortener

Week 2:
└─ 2025-05-19: Dynamic Programming Fundamentals
└─ 2025-05-22: Behavioral Interview Practice

Week 3:
└─ 2025-05-26: Mock Interview with Exponent
└─ 2025-05-29: Final Review Session

Week 4:
└─ 2025-06-02: Company-specific Deep Dive (Google)
└─ 2025-06-05: Last-minute Confidence Check
```

## Tips for Success

### Before Task Due Dates
1. **Realistic Assessment**: Choose reasonable due dates with adequate prep time
2. **Focused Goals**: Make task descriptions specific and measurable
3. **Variety**: Mix different interview types (technical, system design, behavioral)

### During Readiness Assessment
1. **Honest Feedback**: Your ratings help identify improvement areas
2. **Specific Examples**: Reference actual topics or problems in feedback
3. **Actionable Insights**: Note what helped you prepare effectively

### After Submission
1. **Review Patterns**: Look for consistent weak areas across tasks
2. **Adjust Strategy**: If readiness consistently low, increase prep time
3. **Celebrate Progress**: Track improvement in readiness levels over time

## Data Schema

### Task Object
```typescript
{
  id: string              // Unique identifier
  title: string           // Task name (required)
  description?: string    // Task details
  dueDate: Date          // Due date (required)
  readinessLevel?: 1-5   // User's readiness rating
  feedback?: string      // User's experience feedback
  isCompleted: boolean   // Whether task is done
  createdAt: Date        // Creation timestamp
}
```

### Readiness Response Object
```typescript
{
  taskId: string         // Associated task ID
  readinessLevel: 1-5    // How ready (1=not ready, 5=very ready)
  feedback: string       // User's experience description
  responseDate: Date     // When response was submitted
}
```

## API Reference

### Create Task
```bash
POST /tasks
{
  "title": "System Design Interview",
  "description": "Prepare for distributed systems discussion",
  "due_date": "2025-06-01"
}
```

### Submit Readiness
```bash
POST /tasks/{taskId}/readiness
{
  "readiness_level": 4,
  "feedback": "Felt confident explaining trade-offs"
}
```

### Get Readiness History
```bash
GET /readiness?task_id={taskId}
```

## Browser Compatibility

- ✅ Chrome/Edge 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Mobile browsers (iOS Safari, Chrome Mobile)

## Troubleshooting

### Tasks Not Saving?
- Check browser localStorage is enabled
- Ensure you're logged in
- Try refreshing the page

### Readiness Dialog Not Appearing?
- Ensure you've created tasks
- Check that today's date matches a task's due date
- May need to manually create the task for today

### Want to Clear All Data?
- Click task delete button for individual tasks
- Clear browser data to reset all (⚠️ will delete all tasks)

## Future Enhancements

Planned features:
- ✨ Backend persistence with database
- 📊 Advanced analytics and insights
- 📧 Email reminders before task due dates
- 🔄 Sync across devices
- 📈 Readiness trend charts
- 🎯 AI recommendations based on feedback
- 🏆 Achievement badges for consistent preparation

## Support

For issues or feature requests:
- Check this documentation
- Review recent task entries to ensure data is correct
- Consider cloud backup if using critical prep data
