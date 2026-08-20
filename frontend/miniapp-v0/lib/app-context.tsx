'use client'

import { createContext, useContext, useState, useCallback, useEffect, useRef, type ReactNode } from 'react'
import type { AppState, BootstrapResponse, FeedDeepLink, FeedItem, PromptItem, PromptPreset, SavedReference, ScenarioType, Task, TaskDetail, UploadedFile, VideoPromptPreset, WorkspacePanel } from './types'
import { mockAppState, mockImageModels, mockVideoModels } from './mock-data'
import { bootstrapApp, fetchFeedItem, fetchPromptDetail, fetchTaskDetail, getInitData, getStartParamFallback, hasTelegramInitData, waitForTelegramInitData } from './api'
import { parseMiniAppStartParam } from './start-params'
import { isVideoTrendItem, resolveTrendSettings } from './trend-settings'

interface AppContextType {
  state: AppState
  selectedTask: Task | null
  taskDetail: TaskDetail | null
  isTaskDetailOpen: boolean
  isBalanceOpen: boolean
  activeWorkspace: WorkspacePanel | null
  feedDeepLink: FeedDeepLink | null
  promptPreset: PromptPreset | null
  videoPromptPreset: VideoPromptPreset | null
  trendToRun: PromptItem | null
  viewedProfileCode: string | null
  activeTab: number
  setActiveTab: (tab: number) => void
  openProfile: (referralCode?: string | null) => void
  selectTask: (task: Task | null) => void
  closeTaskDetail: () => void
  openBalance: () => void
  closeBalance: () => void
  openWorkspace: (panel: WorkspacePanel) => void
  closeWorkspace: () => void
  consumeFeedDeepLink: () => void
  refreshTasks: () => Promise<void>
  setCredits: (amount: number) => void
  addTask: (task: Task) => void
  updateTask: (taskId: string, patch: Partial<Task>) => void
  setTaskDetail: (detail: TaskDetail | null) => void
  addSavedReference: (file: UploadedFile) => void
  setPromptPreset: (preset: PromptPreset | null) => void
  setVideoPromptPreset: (preset: VideoPromptPreset | null) => void
  setTrendToRun: (trend: PromptItem | null) => void
}

const AppContext = createContext<AppContextType | null>(null)

const imageModelDefaults = new Map(mockImageModels.map((model) => [model.id, model]))
const videoModelDefaults = new Map(mockVideoModels.map((model) => [model.id, model]))
const telegramLockedMessage = 'Откройте Mini App через Telegram. В обычном браузере генерации и история не запускаются.'
const videoScenarios = new Set<ScenarioType>(['text', 'imgtxt', 'video', 'avatar', 'audio', 'character'])

function normalizeVideoScenario(value?: string | null): ScenarioType {
  return videoScenarios.has(value as ScenarioType) ? (value as ScenarioType) : 'text'
}

function createLockedState(message: string | null = telegramLockedMessage, isLoading = false): AppState {
  return {
    ...mockAppState,
    mode: 'locked',
    isLoading,
    error: message,
    user: {
      firstName: 'Telegram',
      lastName: '',
      username: '',
      photoUrl: '',
      referralCode: '',
      profileLink: '',
      referralLink: '',
      channelUrl: '',
      promptRepeatBalanceRub: 0,
      promptRepeatTotalRub: 0,
      botUsername: '',
      credits: 0,
      isAdmin: false,
    },
    imageModels: [],
    videoModels: [],
    recentTasks: [],
    savedReferences: [],
    paymentPackages: mockAppState.paymentPackages,
    lastSync: null,
  }
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function normalizeImageModels(models: BootstrapResponse['image_models']) {
  return models.map((model) => {
    const fallback = imageModelDefaults.get(model.id)
    if (!fallback) return model
    return {
      ...fallback,
      ...model,
      ratios: model.ratios?.length ? model.ratios : fallback.ratios,
      qualities: model.qualities ?? fallback.qualities,
      quality_costs:
        model.quality_costs && Object.keys(model.quality_costs).length
          ? model.quality_costs
          : fallback.quality_costs,
      supports_nsfw_checker:
        model.supports_nsfw_checker ?? fallback.supports_nsfw_checker,
      supports_nsfw_mode:
        model.supports_nsfw_mode ?? fallback.supports_nsfw_mode,
    }
  })
}

function normalizeVideoModels(models: BootstrapResponse['video_models']) {
  return models.map((model) => {
    const fallback = videoModelDefaults.get(model.id)
    if (!fallback) return model
    return {
      ...fallback,
      ...model,
      ratios: model.ratios?.length ? model.ratios : fallback.ratios,
      durations: model.durations?.length ? model.durations : fallback.durations,
      supports: model.supports?.length ? model.supports : fallback.supports,
      costs: Object.keys(model.costs || {}).length ? model.costs : fallback.costs,
      quality_costs:
        model.quality_costs && Object.keys(model.quality_costs).length
          ? model.quality_costs
          : fallback.quality_costs,
    }
  })
}

function toUploadedReference(reference: SavedReference): UploadedFile {
  return {
    id: `saved_${reference.id}`,
    name: reference.filename || `reference_${reference.id}`,
    url: reference.url,
    type: reference.kind,
    size: 0,
    saved_reference_id: reference.id,
    created_at: reference.created_at || null,
    source: reference.source,
  }
}

function feedReferenceToUploadedFile(url: string, index: number, type: 'image' | 'video' = 'image'): UploadedFile {
  const cleanUrl = String(url || '').trim()
  const urlParts = cleanUrl.split('/')
  const rawName = urlParts[urlParts.length - 1] || `reference_${index + 1}.jpg`
  return {
    id: `feed_ref_${index}_${rawName}`,
    name: `Реф ${index + 1}`,
    url: cleanUrl,
    type,
    size: 0,
    source: 'feed-remix',
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(() => createLockedState(null, true))
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [taskDetail, setTaskDetail] = useState<TaskDetail | null>(null)
  const [isTaskDetailOpen, setIsTaskDetailOpen] = useState(false)
  const [isBalanceOpen, setIsBalanceOpen] = useState(false)
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspacePanel | null>(null)
  const [feedDeepLink, setFeedDeepLink] = useState<FeedDeepLink | null>(null)
  const [promptPreset, setPromptPreset] = useState<PromptPreset | null>(null)
  const [videoPromptPreset, setVideoPromptPreset] = useState<VideoPromptPreset | null>(null)
  const [trendToRun, setTrendToRun] = useState<PromptItem | null>(null)
  const [viewedProfileCode, setViewedProfileCode] = useState<string | null>(null)
  const [activeTab, setActiveTabState] = useState(0)
  const pollRef = useRef<number | null>(null)
  const handledStartParamRef = useRef<string | null>(null)

  const applyTaskDetail = useCallback((detail: TaskDetail | null) => {
    setTaskDetail(detail)
  }, [])

  const applyBootstrap = useCallback((data: BootstrapResponse) => {
    setSelectedTask((current) => {
      if (!current) return current
      const fresh = data.recent_tasks.find((task) => task.task_id === current.task_id)
      return fresh ? { ...current, ...fresh } : current
    })
    setTaskDetail((current) => {
      if (!current) return current
      const fresh = data.recent_tasks.find((task) => task.task_id === current.task_id)
      return fresh ? { ...current, ...fresh } : current
    })
    setState({
      mode: 'live',
      isLoading: false,
      error: null,
      user: {
        telegramId: data.telegram_id,
        firstName: data.first_name || 'Пользователь',
        lastName: data.last_name || '',
        username: data.telegram_username || '',
        photoUrl: data.photo_url || '',
        referralCode: data.referral_code || '',
        profileLink: data.profile_link || '',
        referralLink: data.referral_link || '',
        channelUrl: data.channel_url || '',
        promptRepeatBalanceRub: data.prompt_repeat_balance_rub || 0,
        promptRepeatTotalRub: data.prompt_repeat_total_rub || 0,
        botUsername: data.bot_username || '',
        credits: data.credits,
        isAdmin: data.is_admin,
      },
      imageModels: normalizeImageModels(data.image_models),
      videoModels: normalizeVideoModels(data.video_models),
      recentTasks: data.recent_tasks,
      savedReferences: (data.saved_references || []).map(toUploadedReference),
      paymentPackages:
        data.payment_packages?.length ? data.payment_packages : mockAppState.paymentPackages,
      lastSync: new Date(),
    })
  }, [])

  const applyLockedState = useCallback((message: string | null = telegramLockedMessage) => {
    setSelectedTask(null)
    setTaskDetail(null)
    setIsTaskDetailOpen(false)
    setFeedDeepLink(null)
    setPromptPreset(null)
    setVideoPromptPreset(null)
    setTrendToRun(null)
    setViewedProfileCode(null)
    setActiveTabState(0)
    setState(createLockedState(message, false))
  }, [])

  const applyBootstrapErrorState = useCallback((message: string) => {
    setState(prev => ({
      ...(prev.mode === 'live' ? prev : createLockedState(message, false)),
      isLoading: false,
      error: message,
      user: {
        ...prev.user,
        credits: prev.mode === 'live' ? prev.user.credits : 0,
      },
      recentTasks: prev.mode === 'live' ? prev.recentTasks : [],
      savedReferences: prev.mode === 'live' ? prev.savedReferences : [],
      paymentPackages:
        prev.mode === 'live' && prev.paymentPackages.length
          ? prev.paymentPackages
          : mockAppState.paymentPackages,
      lastSync: prev.mode === 'live' ? prev.lastSync : null,
    }))
  }, [])

  const selectTask = useCallback((task: Task | null) => {
    setSelectedTask(task)
    if (task) {
      setIsTaskDetailOpen(true)
      if (hasTelegramInitData()) {
        fetchTaskDetail(task.task_id)
          .then((detail) => applyTaskDetail(detail))
          .catch(() => {
            applyTaskDetail({
              ...task,
              prompt: task.prompt_preview,
            })
          })
      } else {
        applyTaskDetail({
          ...task,
          prompt: task.prompt_preview,
        })
      }
    } else {
      applyTaskDetail(null)
      setIsTaskDetailOpen(false)
    }
  }, [applyTaskDetail])

  const closeTaskDetail = useCallback(() => {
    setIsTaskDetailOpen(false)
    setTimeout(() => {
      setSelectedTask(null)
      applyTaskDetail(null)
    }, 300)
  }, [applyTaskDetail])

  const openBalance = useCallback(() => {
    setIsBalanceOpen(true)
  }, [])

  const closeBalance = useCallback(() => {
    setIsBalanceOpen(false)
  }, [])

  const openWorkspace = useCallback((panel: WorkspacePanel) => {
    setActiveWorkspace(panel)
  }, [])

  const closeWorkspace = useCallback(() => {
    setActiveWorkspace(null)
  }, [])

  const consumeFeedDeepLink = useCallback(() => {
    setFeedDeepLink(null)
  }, [])

  const setActiveTab = useCallback((tab: number) => {
    if (tab === 7) {
      setViewedProfileCode(null)
    }
    setActiveTabState(tab)
  }, [])

  const openProfile = useCallback((referralCode?: string | null) => {
    const code = String(referralCode || '').trim().toUpperCase()
    setViewedProfileCode(code || null)
    setActiveTabState(7)
  }, [])

  const refreshTasks = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true, error: null }))
    const hasInitData = hasTelegramInitData() || await waitForTelegramInitData(5000)
    if (!hasInitData) {
      applyLockedState('Telegram не передал данные входа. Закройте окно и откройте Mini App заново из Telegram.')
      return
    }
    try {
      const data = await bootstrapApp()
      applyBootstrap(data)
    } catch {
      applyBootstrapErrorState('Не удалось обновить данные прямо сейчас. Показываю только подтверждённые данные без демо-подстановок.')
    }
  }, [applyBootstrap, applyBootstrapErrorState, applyLockedState])

  const applyFeedRemix = useCallback((item: FeedItem) => {
    if (item.gen_type === 'video') {
      const modelExists = state.videoModels.some((model) => model.id === item.model)
      const imageReferences = item.references_hidden ? [] : (item.reference_images || []).map((url, index) => feedReferenceToUploadedFile(url, index))
      const videoReferences = item.references_hidden ? [] : (item.reference_videos || []).map((url, index) => feedReferenceToUploadedFile(url, index, 'video'))
      const scenario = imageReferences.length
        ? 'imgtxt'
        : videoReferences.length
          ? 'video'
          : normalizeVideoScenario(item.scenario)
      setVideoPromptPreset({
        title: 'Повторить видео из ссылки',
        prompt: item.prompt || '',
        model: modelExists ? item.model : state.videoModels[0]?.id || 'v3_pro',
        scenario,
        ratio: item.aspect_ratio || '16:9',
        duration: item.duration || 5,
        sourceFeedGenId: item.id,
        promptHidden: item.prompt_hidden,
        initialStartImage: scenario === 'imgtxt' ? imageReferences.slice(0, 1) : [],
        initialPhotoReferences: scenario === 'imgtxt' ? imageReferences.slice(1) : imageReferences,
        initialVideoReferences: videoReferences,
      })
      setActiveTabState(2)
      return
    }

    const modelExists = state.imageModels.some((model) => model.id === item.model)
    setPromptPreset({
      promptId: null,
      title: 'Повторить публикацию из ссылки',
      prompt: item.prompt || '',
      model: modelExists ? item.model : state.imageModels[0]?.id || 'banana_pro',
      ratio: item.aspect_ratio || '1:1',
      sourceFeedGenId: item.id,
      promptHidden: item.prompt_hidden,
      initialReferences: item.is_mine && !item.references_hidden
        ? (item.reference_images || []).map((url, index) => feedReferenceToUploadedFile(url, index))
        : [],
    })
    setActiveTabState(1)
  }, [state.imageModels, state.videoModels])

  useEffect(() => {
    if (state.mode !== 'live' || state.isLoading) return

    const rawStartParam = getStartParamFallback()
    if (!rawStartParam || handledStartParamRef.current === rawStartParam) return

    const target = parseMiniAppStartParam(rawStartParam)
    if (!target) {
      handledStartParamRef.current = rawStartParam
      return
    }
    const startTarget = target

    let cancelled = false
    async function routeStartParam() {
      try {
        if (startTarget.kind === 'ref') {
          setActiveTabState(0)
          return
        }

        if (startTarget.kind === 'profile') {
          openProfile(startTarget.referralCode)
          return
        }

        if (startTarget.kind === 'feed' || startTarget.kind === 'remix') {
          const item = await fetchFeedItem(startTarget.genId)
          if (cancelled) return
          if (startTarget.kind === 'remix') {
            applyFeedRemix(item)
            return
          }
          setFeedDeepLink({ item, action: 'preview' })
          if (item.publication_scope === 'profile') {
            setViewedProfileCode(String(item.author_referral_code || '').trim().toUpperCase() || null)
            setActiveTabState(7)
          } else {
            setActiveTabState(4)
          }
          return
        }

        if (startTarget.kind === 'prompt') {
          const prompt = await fetchPromptDetail(startTarget.promptId)
          if (cancelled) return
          const isTrend = (prompt.tags || []).some(
            (tag) => String(tag).toLowerCase() === 'trend',
          )
          const isVideoTrend = isVideoTrendItem(prompt, state.videoModels)

          if (isVideoTrend) {
            const settings = resolveTrendSettings(
              prompt,
              state.imageModels,
              state.videoModels,
            )
            setVideoPromptPreset({
              title: prompt.title,
              prompt: prompt.prompt_text,
              model: settings.model || state.videoModels[0]?.id || 'v3_pro',
              scenario: normalizeVideoScenario(settings.scenario),
              ratio: settings.ratio || '16:9',
              duration: settings.duration || undefined,
            })
            setActiveTabState(2)
            return
          }

          if (isTrend) {
            setTrendToRun(prompt)
            setActiveTabState(5)
            return
          }

          setPromptPreset({
            promptId: prompt.id,
            title: prompt.title,
            prompt: prompt.prompt_text,
            model: prompt.model,
          })
          setActiveTabState(1)
          return
        }

        if (startTarget.kind === 'task') {
          const detail = await fetchTaskDetail(startTarget.taskId)
          if (cancelled) return
          setSelectedTask(detail)
          setTaskDetail(detail)
          setIsTaskDetailOpen(true)
        }
      } catch (error) {
        if (!cancelled) {
          setState(prev => ({
            ...prev,
            error: getErrorMessage(error, 'Не удалось открыть ссылку Mini App.'),
          }))
        }
      } finally {
        if (!cancelled) {
          handledStartParamRef.current = rawStartParam
        }
      }
    }

    routeStartParam()
    return () => {
      cancelled = true
    }
  }, [applyFeedRemix, openProfile, state.isLoading, state.mode, state.videoModels])

  const setCredits = useCallback((amount: number) => {
    setState(prev => ({
      ...prev,
      user: {
        ...prev.user,
        credits: amount,
      },
    }))
  }, [])

  const addTask = useCallback((task: Task) => {
    setState(prev => ({
      ...prev,
      recentTasks: [task, ...prev.recentTasks],
    }))
  }, [])

  const updateTask = useCallback((taskId: string, patch: Partial<Task>) => {
    setState(prev => ({
      ...prev,
      recentTasks: prev.recentTasks.map(task =>
        task.task_id === taskId ? { ...task, ...patch } : task
      ),
    }))
    setSelectedTask(prev => (prev?.task_id === taskId ? { ...prev, ...patch } : prev))
    setTaskDetail(prev => (prev?.task_id === taskId ? { ...prev, ...patch } : prev))
  }, [])

  const addSavedReference = useCallback((file: UploadedFile) => {
    if (!file.url || !file.type) return
    setState(prev => {
      const exists = prev.savedReferences.some(item => item.url === file.url)
      if (exists) {
        return prev
      }
      return {
        ...prev,
        savedReferences: [
          {
            ...file,
            id: file.saved_reference_id ? `saved_${file.saved_reference_id}` : file.id,
            size: file.size || 0,
          },
          ...prev.savedReferences,
        ],
      }
    })
  }, [])

  useEffect(() => {
    refreshTasks()
  }, [refreshTasks])

  useEffect(() => {
    if (state.mode !== 'live') return
    let syncing = false

    const syncResults = async () => {
      if (syncing || document.visibilityState !== 'visible' || !getInitData()) return
      syncing = true
      try {
        const data = await bootstrapApp()
        applyBootstrap(data)
      } catch {
        // Keep the last confirmed state; the next tick or focus event retries.
      } finally {
        syncing = false
      }
    }

    const onVisible = () => {
      if (document.visibilityState === 'visible') void syncResults()
    }
    window.addEventListener('focus', onVisible)
    document.addEventListener('visibilitychange', onVisible)
    const timer = window.setInterval(() => void syncResults(), 5_000)
    return () => {
      window.removeEventListener('focus', onVisible)
      document.removeEventListener('visibilitychange', onVisible)
      window.clearInterval(timer)
    }
  }, [applyBootstrap, state.mode])

  useEffect(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (!isTaskDetailOpen || !selectedTask || selectedTask.status !== 'pending') {
      return
    }
    if (!getInitData()) {
      return
    }
    pollRef.current = window.setInterval(async () => {
      try {
        const detail = await fetchTaskDetail(selectedTask.task_id)
        applyTaskDetail(detail)
        updateTask(selectedTask.task_id, {
          status: detail.status,
          result_url: detail.result_url || null,
          duration: detail.duration ?? undefined,
        })
        if (detail.status !== 'pending' && pollRef.current) {
          window.clearInterval(pollRef.current)
          pollRef.current = null
        }
      } catch {
        // Keep current task state; next manual refresh can recover.
      }
    }, 5000)

    return () => {
      if (pollRef.current) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [applyTaskDetail, isTaskDetailOpen, selectedTask, updateTask])

  return (
    <AppContext.Provider
      value={{
        state,
        selectedTask,
        taskDetail,
        isTaskDetailOpen,
        isBalanceOpen,
        activeWorkspace,
        feedDeepLink,
        promptPreset,
        videoPromptPreset,
        trendToRun,
        viewedProfileCode,
        activeTab,
        setActiveTab,
        openProfile,
        selectTask,
        closeTaskDetail,
        openBalance,
        closeBalance,
        openWorkspace,
        closeWorkspace,
        consumeFeedDeepLink,
        refreshTasks,
        setCredits,
        addTask,
        updateTask,
        setTaskDetail: applyTaskDetail,
        addSavedReference,
        setPromptPreset,
        setVideoPromptPreset,
        setTrendToRun,
      }}
    >
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const context = useContext(AppContext)
  if (!context) {
    throw new Error('useApp must be used within AppProvider')
  }
  return context
}
