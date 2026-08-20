'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { UploadedFile } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Upload, X, Loader2, Video, Music, Plus } from 'lucide-react'
import { sendMiniAppClientLog } from '@/lib/api'

interface UploadAreaProps {
  files: UploadedFile[]
  onFilesChange: (files: UploadedFile[]) => void
  maxFiles: number
  accept: string
  required?: boolean
  onUpload?: (file: File) => Promise<UploadedFile>
  libraryFiles?: UploadedFile[]
  libraryLabel?: string
}

const MEDIA_MIME_BY_EXTENSION: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  heic: 'image/heic',
  heif: 'image/heif',
  avif: 'image/avif',
  mp4: 'video/mp4',
  mov: 'video/quicktime',
  m4v: 'video/x-m4v',
  webm: 'video/webm',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  m4a: 'audio/mp4',
  aac: 'audio/aac',
  ogg: 'audio/ogg',
}

function normalizedBrowserFile(file: File): File {
  const declaredType = String(file.type || '').toLowerCase()
  if (declaredType && declaredType !== 'application/octet-stream') return file

  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const inferredType = MEDIA_MIME_BY_EXTENSION[extension]
  if (!inferredType) return file

  return new File([file], file.name, {
    type: inferredType,
    lastModified: file.lastModified,
  })
}

function matchesAcceptedType(file: File, accept: string) {
  const normalized = normalizedBrowserFile(file)
  if (accept.startsWith('image/')) return normalized.type.startsWith('image/')
  if (accept.startsWith('video/')) return normalized.type.startsWith('video/')
  if (accept.startsWith('audio/')) return normalized.type.startsWith('audio/')
  return true
}

export function UploadArea({
  files,
  onFilesChange,
  maxFiles,
  accept,
  required,
  onUpload,
  libraryFiles = [],
  libraryLabel = 'Сохранённые референсы',
}: UploadAreaProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const filesRef = useRef(files)
  const [isDragging, setIsDragging] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  useEffect(() => {
    filesRef.current = files
  }, [files])

  const publishFiles = useCallback((nextFiles: UploadedFile[]) => {
    filesRef.current = nextFiles
    onFilesChange(nextFiles)
  }, [onFilesChange])

  const handleFiles = useCallback(async (fileList: FileList | File[]) => {
    setUploadError(null)

    for (const sourceFile of Array.from(fileList)) {
      const file = normalizedBrowserFile(sourceFile)
      sendMiniAppClientLog('upload-file-selected', {
        accept,
        file_name: file.name,
        file_type: file.type,
        file_size: file.size,
      })
      const currentFiles = filesRef.current
      if (currentFiles.length >= maxFiles) break
      if (!matchesAcceptedType(file, accept)) {
        sendMiniAppClientLog('upload-file-rejected', {
          accept,
          file_name: file.name,
          file_type: file.type,
          file_size: file.size,
          reason: 'type_mismatch',
        })
        setUploadError(
          accept.startsWith('image/')
            ? 'Можно загружать только изображения'
            : accept.startsWith('video/')
              ? 'Можно загружать только видео'
              : 'Можно загружать только аудио'
        )
        continue
      }

      const localUrl = file.type.startsWith('image/') || file.type.startsWith('video/')
        ? URL.createObjectURL(file)
        : ''
      const pendingFile: UploadedFile = {
        id: `file_${Date.now()}_${Math.random().toString(36).slice(2)}`,
        name: file.name,
        url: localUrl,
        preview_url: localUrl,
        type: file.type.startsWith('video/') ? 'video' : file.type.startsWith('audio/') ? 'audio' : 'image',
        size: file.size,
        uploading: true,
      }

      publishFiles([...filesRef.current, pendingFile])

      try {
        const uploadedFile = onUpload
          ? await onUpload(file)
          : {
              ...pendingFile,
              uploading: false,
            }
        const latestFiles = filesRef.current
        const nextFiles = latestFiles.map((item) =>
          item.id === pendingFile.id
            ? { ...uploadedFile, id: pendingFile.id, preview_url: localUrl || uploadedFile.preview_url, uploading: false }
            : item
        )
        publishFiles(nextFiles)
      } catch (error) {
        publishFiles(filesRef.current.filter((item) => item.id !== pendingFile.id))
        setUploadError(
          error instanceof Error ? error.message : 'Не удалось загрузить файл'
        )
        if (localUrl) URL.revokeObjectURL(localUrl)
      }
    }
  }, [accept, maxFiles, onUpload, publishFiles])

  const handleDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(false)
    void handleFiles(event.dataTransfer.files)
  }, [handleFiles])

  const handleRemove = (id: string) => {
    const removed = filesRef.current.find((file) => file.id === id)
    if (removed?.url.startsWith('blob:')) URL.revokeObjectURL(removed.url)
    if (removed?.preview_url?.startsWith('blob:') && removed.preview_url !== removed.url) {
      URL.revokeObjectURL(removed.preview_url)
    }
    publishFiles(filesRef.current.filter((file) => file.id !== id))
  }

  const canUploadMore = files.length < maxFiles
  const availableLibraryFiles = libraryFiles.filter((item) => !files.some((selected) => selected.url === item.url))

  const handleAddFromLibrary = (file: UploadedFile) => {
    if (!canUploadMore) return
    publishFiles([...filesRef.current, { ...file, id: `${file.id}_${Date.now()}` }])
    setUploadError(null)
  }

  return (
    <div className="space-y-3" aria-busy={files.some((file) => file.uploading)}>
      {canUploadMore && (
        <div
          onPointerDown={() => {
            sendMiniAppClientLog('upload-area-pointer-down', { accept })
          }}
          onDragOver={(event) => {
            event.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={cn(
            'relative flex flex-col items-center justify-center',
            'p-6 rounded-xl border-2 border-dashed cursor-pointer',
            'transition-all duration-200',
            isDragging
              ? 'border-gold bg-gold/5'
              : required
                ? 'border-gold/50 bg-gold/5 hover:border-gold hover:bg-gold/10'
                : 'border-border/50 bg-secondary/30 hover:border-border hover:bg-secondary/50'
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept={accept}
            multiple={maxFiles > 1}
            onClick={() => {
              sendMiniAppClientLog('upload-input-click', { accept })
            }}
            onChange={(event) => {
              const selectedFiles = Array.from(event.target.files || [])
              event.target.value = ''
              if (selectedFiles.length > 0) {
                void handleFiles(selectedFiles)
                return
              }
              sendMiniAppClientLog('upload-input-change-empty', { accept })
            }}
            className={cn(
              'relative z-10 mt-4 block w-full max-w-xs cursor-pointer rounded-lg border border-border/60',
              'bg-background/80 px-3 py-2 text-sm text-foreground',
              'file:mr-3 file:rounded-md file:border-0 file:bg-gold file:px-3 file:py-1.5',
              'file:text-sm file:font-medium file:text-primary-foreground'
            )}
          />

          <div className={cn(
            'w-12 h-12 rounded-xl flex items-center justify-center mb-3',
            required ? 'bg-gold/20' : 'bg-secondary/80'
          )}>
            <Upload className={cn('w-6 h-6', required ? 'text-gold' : 'text-muted-foreground')} />
          </div>

          <p className="text-sm text-foreground mb-1">
            {isDragging ? 'Отпустите файлы' : 'Нажмите или перетащите'}
          </p>
          <p className="text-xs text-muted-foreground">
            Макс. {maxFiles} {maxFiles === 1 ? 'файл' : 'файла'}
          </p>
        </div>
      )}

      {availableLibraryFiles.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{libraryLabel}</p>
            <span className="text-[11px] text-muted-foreground">Можно добавить без повторной загрузки</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {availableLibraryFiles.slice(0, Math.max(0, maxFiles - files.length) + 8).map((file) => (
              <button
                key={file.id}
                type="button"
                onClick={() => handleAddFromLibrary(file)}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-all duration-200',
                  'border-border/50 bg-secondary/40 text-foreground hover:border-gold/40 hover:bg-secondary/70'
                )}
              >
                {file.type === 'image' ? (
                  <img src={file.url} alt="" className="h-7 w-7 rounded object-cover" />
                ) : (
                  <div className="flex h-7 w-7 items-center justify-center rounded bg-secondary">
                    {file.type === 'audio' ? (
                      <Music className="h-3.5 w-3.5 text-cyan" />
                    ) : (
                      <Video className="h-3.5 w-3.5 text-cyan" />
                    )}
                  </div>
                )}
                <span className="max-w-[120px] truncate">{file.name}</span>
                <Plus className="h-3.5 w-3.5 text-gold" />
              </button>
            ))}
          </div>
        </div>
      )}

      {files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {files.map((file) => (
            <div
              key={file.id}
              className={cn(
                'group relative flex items-center gap-2 pl-2 pr-1 py-1 rounded-lg',
                'bg-secondary/80 border border-border/50',
                'transition-all duration-200 hover:border-border'
              )}
            >
              <div className="w-8 h-8 rounded overflow-hidden bg-secondary flex-shrink-0">
                {file.uploading ? (
                  <div className="w-full h-full flex items-center justify-center">
                    <Loader2 className="w-4 h-4 text-muted-foreground animate-spin" />
                  </div>
                ) : file.type === 'image' ? (
                  <img src={file.preview_url || file.url} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    {file.type === 'audio' ? (
                      <Music className="w-4 h-4 text-cyan" />
                    ) : (
                      <Video className="w-4 h-4 text-cyan" />
                    )}
                  </div>
                )}
              </div>

              <span className="text-xs text-foreground max-w-[100px] truncate">
                {file.name}
              </span>

              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  handleRemove(file.id)
                }}
                className={cn(
                  'w-6 h-6 rounded flex items-center justify-center',
                  'text-muted-foreground hover:text-foreground hover:bg-secondary',
                  'transition-colors'
                )}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {uploadError && (
        <p className="text-xs text-destructive">{uploadError}</p>
      )}

      <p className="text-xs text-muted-foreground">
        {accept.startsWith('image/')
          ? 'PNG, JPG, WEBP, HEIC. Удаляйте лишние референсы прямо из списка.'
          : 'MP3, WAV, M4A или MP4/MOV для видео-референсов. Держите референсы короткими и чистыми.'}
      </p>
    </div>
  )
}
