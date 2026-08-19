'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { ApiError, miniAppApi, telegramStartParam } from './api'
import { parseDeepLinkIntent, remixInputSeed, tabForDeepLink } from './deep-links'
import type {
  BootstrapResponse,
  Generation,
  ModelDefinition,
  PartnerData,
  Publication,
  PublicProfileView,
  ReferenceItem,
  StarPackage,
  SupportTicket,
  TabId,
  TariffData,
  WorkspaceId,
} from './types'

type AppMode = 'loading' | 'live' | 'locked' | 'error'

type ModelSelectionOptions = {
  input?: Record<string, unknown>
  sourcePublicationId?: string | null
}

interface AppContextValue {
  mode: AppMode
  error: string | null
  bootstrap: BootstrapResponse | null
  activeTab: TabId
  selectedModel: ModelDefinition | null
  draftInput: Record<string, unknown>
  activeWorkspace: WorkspaceId
  generations: Generation[]
  focusedGeneration: Generation | null
  feed: Publication[]
  focusedPublication: Publication | null
  publicProfileView: PublicProfileView | null
  references: ReferenceItem[]
  tariff: TariffData | null
  supportTickets: SupportTicket[]
  partner: PartnerData | null
  starPackages: StarPackage[]
  busy: boolean
  setActiveTab: (tab: TabId) => void
  selectModel: (model: ModelDefinition | null, options?: ModelSelectionOptions) => void
  openWorkspace: (workspace: WorkspaceId) => void
  closeWorkspace: () => void
  openGeneration: (id: string) => Promise<void>
  clearGenerationFocus: () => void
  refreshBootstrap: () => Promise<void>
  refreshGenerations: () => Promise<void>
  refreshFeed: (sort?: string) => Promise<void>
  refreshReferences: () => Promise<void>
  refreshWorkspace: (workspace: Exclude<WorkspaceId, null>) => Promise<void>
  submitModel: (model: ModelDefinition, input: Record<string, unknown>) => Promise<string>
  cancelGeneration: (id: string) => Promise<void>
  publishGeneration: (id: string, scope: 'feed' | 'profile') => Promise<void>
  openStarInvoice: (packageCode: string) => Promise<void>
}

const AppContext = createContext<AppContextValue | null>(null)

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : 'Неизвестная ошибка Happy Fox'
}

function setupTelegram() {
  const webApp = window.Telegram?.WebApp
  try {
    webApp?.ready?.()
    webApp?.expand?.()
    webApp?.setHeaderColor?.('#090909')
    webApp?.setBackgroundColor?.('#070707')
    webApp?.setBottomBarColor?.('#090909')
  } catch {
    // Telegram bridge is optional in browser tests.
  }
}

function upsertGeneration(rows: Generation[], generation: Generation) {
  return [generation, ...rows.filter((item) => item.id !== generation.id)]
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<AppMode>('loading')
  const [error, setError] = useState<string | null>(null)
  const [bootstrap, setBootstrap] = useState<BootstrapResponse | null>(null)
  const [activeTab, setActiveTabState] = useState<TabId>('home')
  const [selectedModel, setSelectedModel] = useState<ModelDefinition | null>(null)
  const [draftInput, setDraftInput] = useState<Record<string, unknown>>({})
  const [sourcePublicationId, setSourcePublicationId] = useState<string | null>(null)
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceId>(null)
  const [generations, setGenerations] = useState<Generation[]>([])
  const [focusedGeneration, setFocusedGeneration] = useState<Generation | null>(null)
  const [feed, setFeed] = useState<Publication[]>([])
  const [focusedPublication, setFocusedPublication] = useState<Publication | null>(null)
  const [publicProfileView, setPublicProfileView] = useState<PublicProfileView | null>(null)
  const [references, setReferences] = useState<ReferenceItem[]>([])
  const [tariff, setTariff] = useState<TariffData | null>(null)
  const [supportTickets, setSupportTickets] = useState<SupportTicket[]>([])
  const [partner, setPartner] = useState<PartnerData | null>(null)
  const [starPackages, setStarPackages] = useState<StarPackage[]>([])
  const [busy, setBusy] = useState(false)
  const booted = useRef(false)

  const applyBootstrap = useCallback((data: BootstrapResponse) => {
    setBootstrap(data)
    setGenerations(data.recent ?? [])
    setMode('live')
    setError(null)
  }, [])

  const refreshBootstrap = useCallback(async () => {
    const data = await miniAppApi.bootstrap()
    applyBootstrap(data)
  }, [applyBootstrap])

  useEffect(() => {
    if (booted.current) return
    booted.current = true
    setupTelegram()
    const startParam = telegramStartParam()
    const intent = parseDeepLinkIntent(startParam)
    if (intent) setActiveTabState(tabForDeepLink(intent))

    void (async () => {
      try {
        await miniAppApi.authenticate()
        const data = await miniAppApi.bootstrap()
        applyBootstrap(data)
        if (!intent) return

        if (intent.kind === 'model') {
          const model = data.models.find((item) => item.slug === intent.value || item.ui_key === intent.value)
          if (!model) throw new Error('Модель из ссылки недоступна.')
          setSelectedModel(model)
          return
        }

        if (intent.kind === 'generation') {
          const generation = await miniAppApi.generation(intent.value)
          setFocusedGeneration(generation)
          setGenerations((current) => upsertGeneration(current, generation))
          return
        }

        if (intent.kind === 'profile') {
          const [profile, publications] = await Promise.all([
            miniAppApi.publicProfile(intent.value),
            miniAppApi.profilePublications(intent.value, 30, 0),
          ])
          setPublicProfileView({ profile, publications: publications.items })
          return
        }

        if (intent.kind === 'post') {
          const publication = await miniAppApi.publication(intent.value)
          setFocusedPublication(publication)
          setFeed([publication])
          setActiveWorkspace('feed')
          return
        }

        const source = await miniAppApi.remixSource(intent.value)
        const model = data.models.find((item) => item.slug === source.model_slug || item.ui_key === source.model_slug)
        if (!model) throw new Error('Модель исходной публикации сейчас недоступна для Remix.')
        setDraftInput(remixInputSeed(model, source))
        setSourcePublicationId(source.publication_id)
        setSelectedModel(model)
        setActiveTabState('create')
      } catch (reason) {
        const message = messageOf(reason)
        setError(message)
        setMode(reason instanceof ApiError && reason.status === 401 ? 'locked' : 'error')
      }
    })()
  }, [applyBootstrap])

  const setActiveTab = useCallback((tab: TabId) => {
    setActiveWorkspace(null)
    setActiveTabState(tab)
    if (tab !== 'create') {
      setSelectedModel(null)
      setDraftInput({})
      setSourcePublicationId(null)
    }
    if (tab !== 'works') setFocusedGeneration(null)
    if (tab !== 'profile') setPublicProfileView(null)
    if (tab !== 'services') setFocusedPublication(null)
    try {
      window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light')
    } catch {
      // Ignore bridge failures.
    }
  }, [])

  const selectModel = useCallback((model: ModelDefinition | null, options?: ModelSelectionOptions) => {
    setSelectedModel(model)
    setDraftInput(model ? (options?.input ?? {}) : {})
    setSourcePublicationId(model ? (options?.sourcePublicationId ?? null) : null)
    if (model) setActiveTabState('create')
  }, [])

  const openWorkspace = useCallback((workspace: WorkspaceId) => {
    if (workspace !== 'feed') setFocusedPublication(null)
    setActiveWorkspace(workspace)
  }, [])

  const closeWorkspace = useCallback(() => {
    setActiveWorkspace(null)
    setFocusedPublication(null)
  }, [])

  const openGeneration = useCallback(async (id: string) => {
    const generation = await miniAppApi.generation(id)
    setFocusedGeneration(generation)
    setGenerations((current) => upsertGeneration(current, generation))
  }, [])

  const clearGenerationFocus = useCallback(() => setFocusedGeneration(null), [])

  const refreshGenerations = useCallback(async () => {
    const rows = await miniAppApi.generations(100)
    setGenerations(rows)
    setFocusedGeneration((current) => {
      if (!current) return current
      return rows.find((item) => item.id === current.id) ?? current
    })
  }, [])

  const refreshFeed = useCallback(async (sort = 'recent') => {
    const data = await miniAppApi.feed(sort, 30, 0)
    setFeed(data.items)
    setFocusedPublication(null)
  }, [])

  const refreshReferences = useCallback(async () => {
    const data = await miniAppApi.references(100)
    setReferences(data.items)
  }, [])

  const refreshWorkspace = useCallback(async (workspace: Exclude<WorkspaceId, null>) => {
    setBusy(true)
    try {
      if (workspace === 'balance') {
        const [balance, prices, ledger, packages] = await Promise.all([
          miniAppApi.balance(),
          miniAppApi.prices(),
          miniAppApi.ledger(200),
          miniAppApi.starPackages().catch(() => ({ items: [] as StarPackage[] })),
        ])
        setBootstrap((current) => (current ? { ...current, balance, prices, ledger } : current))
        setStarPackages(packages.items)
      } else if (workspace === 'feed') {
        if (!focusedPublication) await refreshFeed()
      } else if (workspace === 'references') {
        await refreshReferences()
      } else if (workspace === 'tariff') {
        setTariff(await miniAppApi.tariff())
      } else if (workspace === 'support') {
        setSupportTickets((await miniAppApi.support()).items)
      } else if (workspace === 'partner') {
        setPartner(await miniAppApi.partner())
      }
    } finally {
      setBusy(false)
    }
  }, [focusedPublication, refreshFeed, refreshReferences])

  useEffect(() => {
    if (!activeWorkspace || mode !== 'live') return
    void refreshWorkspace(activeWorkspace).catch((reason) => setError(messageOf(reason)))
  }, [activeWorkspace, mode, refreshWorkspace])

  const submitModel = useCallback(async (model: ModelDefinition, input: Record<string, unknown>) => {
    setBusy(true)
    try {
      const validated = await miniAppApi.validateModel(model.slug, input)
      const receipt = await miniAppApi.createTask(model.slug, validated.input, sourcePublicationId)
      await refreshGenerations()
      setActiveTabState('works')
      setSelectedModel(null)
      setDraftInput({})
      setSourcePublicationId(null)
      return receipt.generation_id
    } finally {
      setBusy(false)
    }
  }, [refreshGenerations, sourcePublicationId])

  const cancelGeneration = useCallback(async (id: string) => {
    const generation = await miniAppApi.cancelGeneration(id)
    setFocusedGeneration((current) => (current?.id === generation.id ? generation : current))
    setGenerations((current) => upsertGeneration(current, generation))
  }, [])

  const publishGeneration = useCallback(async (id: string, scope: 'feed' | 'profile') => {
    await miniAppApi.publish(id, scope)
    if (scope === 'feed') await refreshFeed()
  }, [refreshFeed])

  const openStarInvoice = useCallback(async (packageCode: string) => {
    const invoice = await miniAppApi.createStarInvoice(packageCode)
    const webApp = window.Telegram?.WebApp
    if (!webApp?.openInvoice) {
      window.location.href = invoice.invoice_url
      return
    }
    await new Promise<void>((resolve) => {
      webApp.openInvoice?.(invoice.invoice_url, () => resolve())
    })
    await refreshBootstrap()
  }, [refreshBootstrap])

  const value = useMemo<AppContextValue>(() => ({
    mode,
    error,
    bootstrap,
    activeTab,
    selectedModel,
    draftInput,
    activeWorkspace,
    generations,
    focusedGeneration,
    feed,
    focusedPublication,
    publicProfileView,
    references,
    tariff,
    supportTickets,
    partner,
    starPackages,
    busy,
    setActiveTab,
    selectModel,
    openWorkspace,
    closeWorkspace,
    openGeneration,
    clearGenerationFocus,
    refreshBootstrap,
    refreshGenerations,
    refreshFeed,
    refreshReferences,
    refreshWorkspace,
    submitModel,
    cancelGeneration,
    publishGeneration,
    openStarInvoice,
  }), [
    mode,
    error,
    bootstrap,
    activeTab,
    selectedModel,
    draftInput,
    activeWorkspace,
    generations,
    focusedGeneration,
    feed,
    focusedPublication,
    publicProfileView,
    references,
    tariff,
    supportTickets,
    partner,
    starPackages,
    busy,
    setActiveTab,
    selectModel,
    openWorkspace,
    closeWorkspace,
    openGeneration,
    clearGenerationFocus,
    refreshBootstrap,
    refreshGenerations,
    refreshFeed,
    refreshReferences,
    refreshWorkspace,
    submitModel,
    cancelGeneration,
    publishGeneration,
    openStarInvoice,
  ])

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const value = useContext(AppContext)
  if (!value) throw new Error('useApp must be used inside AppProvider')
  return value
}
