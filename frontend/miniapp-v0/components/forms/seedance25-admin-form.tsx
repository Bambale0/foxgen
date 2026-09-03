'use client'

import { Seedance25OfficialForm } from './seedance25-official-form'
import type { Seedance25GenerateResponse } from '@/lib/seedance25-api'
import type { UploadedFile, VideoModel } from '@/lib/types'

interface Props {
  model?: VideoModel
  onQueued?: (result: Seedance25GenerateResponse) => void | Promise<void>
  onSavedReference?: (file: UploadedFile) => void
}

/**
 * Admins use the same Seedance 2.5 provider contract as public users.
 * isAdmin keeps no-charge semantics without preview-only provider fields.
 */
export function Seedance25AdminForm({ model, onQueued, onSavedReference }: Props) {
  return (
    <Seedance25OfficialForm
      model={model}
      credits={0}
      isAdmin
      onQueued={onQueued}
      onSavedReference={onSavedReference}
    />
  )
}
