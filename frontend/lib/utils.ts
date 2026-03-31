import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatApiError(detail: unknown, fallback = 'Something went wrong') {
  if (!detail) {
    return fallback
  }

  if (typeof detail === 'string') {
    return detail
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (!entry) return null
        if (typeof entry === 'string') return entry
        if (typeof entry === 'object') {
          const msg =
            // FastAPI style validation message prioritization
            (entry as { msg?: unknown; message?: unknown }).msg ??
            (entry as { msg?: unknown; message?: unknown }).message
          if (typeof msg === 'string' && msg.trim().length > 0) {
            return msg
          }
        }
        try {
          return JSON.stringify(entry)
        } catch (error) {
          return null
        }
      })
      .filter((msg): msg is string => Boolean(msg))

    if (messages.length > 0) {
      return messages.join(', ')
    }
  }

  if (typeof detail === 'object') {
    const obj = detail as Record<string, unknown>
    if (typeof obj.msg === 'string') {
      return obj.msg
    }
    if (typeof obj.message === 'string') {
      return obj.message
    }
    if (obj.detail) {
      return formatApiError(obj.detail, fallback)
    }
  }

  try {
    return JSON.stringify(detail)
  } catch (error) {
    return fallback
  }
}

export function normalizeGithubUsername(value: string) {
  if (!value) return ''

  let username = value.trim()

  if (username.startsWith('@')) {
    username = username.slice(1)
  }

  if (username.toLowerCase().includes('github.com')) {
    username = username.replace(/^https?:\/\//i, '')
    const parts = username.split('github.com')[1] || ''
    username = parts.replace(/^\//, '').split('/')[0]
  }

  username = username.split(/[?#]/)[0].replace(/\/$/, '').trim()

  return username
}
