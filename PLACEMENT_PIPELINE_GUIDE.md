# Placement Pipeline - Supabase Setup & API Guide

## Supabase SQL Setup

Run this once in Supabase SQL editor:

```sql
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Drives (company placement drives)
CREATE TABLE IF NOT EXISTS placement_drives (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  start_date DATE,
  end_date DATE,
  status TEXT NOT NULL DEFAULT 'Draft',
  eligibility JSONB,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Openings (roles within a drive)
CREATE TABLE IF NOT EXISTS placement_openings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  drive_id UUID REFERENCES placement_drives(id) ON DELETE CASCADE,
  company_name TEXT,
  role_title TEXT NOT NULL,
  location TEXT,
  ctc TEXT,
  employment_type TEXT,
  openings_count INT,
  apply_by DATE,
  status TEXT NOT NULL DEFAULT 'Open',
  eligibility JSONB,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Applications (student applications)
CREATE TABLE IF NOT EXISTS placement_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  drive_id UUID REFERENCES placement_drives(id) ON DELETE SET NULL,
  opening_id UUID REFERENCES placement_openings(id) ON DELETE CASCADE,
  company_name TEXT,
  role_title TEXT,
  user_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Applied',
  notes TEXT,
  applied_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_placement_openings_drive_id ON placement_openings(drive_id);
CREATE INDEX IF NOT EXISTS idx_placement_applications_user_id ON placement_applications(user_id);
CREATE INDEX IF NOT EXISTS idx_placement_applications_opening_id ON placement_applications(opening_id);
```

## Status Values

- Drives: `Draft`, `Open`, `Closed`
- Openings: `Open`, `Closed`
- Applications: `Applied`, `Shortlisted`, `Interview`, `Offer`, `Joined`

## API Endpoints

All endpoints require Bearer auth.

### Drives
- `POST /placements/drives`
- `GET /placements/drives?status=Open`
- `GET /placements/drives/{drive_id}`
- `PUT /placements/drives/{drive_id}`

### Openings
- `POST /placements/openings`
- `GET /placements/openings?drive_id=...&status=Open`
- `GET /placements/openings/{opening_id}`
- `PUT /placements/openings/{opening_id}`

### Applications
- `POST /placements/openings/{opening_id}/apply`
- `GET /placements/applications?status=Applied`
- `PUT /placements/applications/{application_id}/status`

## Notes

- The UI lives at `/placements`.
- Drives and openings are editable by any authenticated user in this initial version.
- Applications default to `Applied` when created.
