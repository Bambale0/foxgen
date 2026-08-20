import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function isHttpUrl(value?: string | null): value is string {
  return /^https?:\/\//i.test((value || '').trim())
}
