export type TabId = 'home' | 'models' | 'create' | 'works' | 'services' | 'profile'
export type WorkspaceId = 'balance' | 'feed' | 'references' | 'tariff' | 'partner' | 'support' | null

export interface TelegramUser {
  id: number
  username?: string | null
  display_name?: string | null
  photo_url?: string | null
  language_code?: string | null
  is_premium?: boolean
}

export interface Balance {
  available_units: number
  reserved_units?: number
  total_units?: number
  currency?: string
}

export interface Price {
  model_slug: string
  amount_units: number
  enabled?: boolean
  [key: string]: unknown
}

export interface JsonSchemaProperty {
  title?: string
  description?: string
  type?: string | string[]
  enum?: Array<string | number | boolean>
  default?: unknown
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  format?: string
  items?: JsonSchemaProperty
  anyOf?: JsonSchemaProperty[]
  oneOf?: JsonSchemaProperty[]
  [key: string]: unknown
}

export interface JsonSchema {
  type?: string
  required?: string[]
  properties?: Record<string, JsonSchemaProperty>
  [key: string]: unknown
}

export interface ModelDefinition {
  slug: string
  ui_key?: string
  variant?: string
  title: string
  family?: string
  media_kind: 'image' | 'video' | 'audio' | string
  capabilities?: string[]
  contract?: string
  defaults?: Record<string, unknown>
  recommended_for?: string[]
  tier?: string
  rank?: number
  enabled?: boolean
  input_schema: JsonSchema
}

export interface GenerationMedia {
  id?: string
  url: string
  content_type: string
  size_bytes?: number
}

export interface Generation {
  id: string
  model_slug: string
  media_kind: string
  status: string
  prompt?: string | null
  created_at?: string | null
  completed_at?: string | null
  error_code?: string | null
  media?: GenerationMedia[]
}

export interface LedgerEntry {
  id?: string
  amount_units?: number
  delta_units?: number
  reason?: string
  created_at?: string
  [key: string]: unknown
}

export interface BootstrapResponse {
  brand: string
  user: TelegramUser
  balance: Balance
  prices: Price[]
  ledger: LedgerEntry[]
  models: ModelDefinition[]
  recent: Generation[]
  features: Record<string, boolean>
  limits: Record<string, number>
}

export interface AuthResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: TelegramUser
}

export interface PublicationAuthor {
  user_id?: number
  slug: string
  display_name?: string | null
  bio?: string | null
}

export interface Publication {
  id: string
  generation_id: string
  author: PublicationAuthor
  scope: string
  active: boolean
  model_slug: string
  media_kind: string
  prompt?: string | null
  prompt_actions_allowed?: boolean
  likes_count: number
  comments_count: number
  remix_count: number
  liked_by_viewer: boolean
  source_publication_id?: string | null
  created_at: string
  media?: Array<{ url: string; content_type: string }>
}

export interface PublicProfile {
  user_id: number
  slug: string
  display_name?: string | null
  bio?: string | null
}

export interface PublicProfileView {
  profile: PublicProfile
  publications: Publication[]
}

export interface RemixSource {
  publication_id: string
  generation_id: string
  author_slug: string
  model_slug: string
  media_kind: string
  prompt?: string | null
  media: Array<{ url: string; content_type: string }>
}

export interface ReferenceItem {
  id: string
  content_type: string
  size_bytes: number
  created_at: string
  preview_url: string
}

export interface SupportMessage {
  id: string
  sender_kind: string
  body: string
  status: string
  created_at: string
}

export interface SupportTicket {
  id: string
  subject: string
  status: string
  priority: string
  created_at: string
  updated_at: string
  messages: SupportMessage[]
}

export interface PartnerProfile {
  joined: boolean
  earned_units: number
  withdrawn_units: number
  pending_units: number
  available_units: number
  referrals_count: number
}

export interface PartnerData {
  profile: PartnerProfile
  withdrawals: Array<{
    id: string
    amount_units: number
    status: string
    destination: string
    reviewed_at?: string | null
    created_at: string
  }>
}

export interface TariffData {
  version: string
  payload: Record<string, unknown>
  published_at: string
}

export interface StarPackage {
  code: string
  title: string
  description: string
  credits_units: number
  base_credits_units: number
  bonus_units: number
  total_credits_units: number
  stars_amount: number
  currency: 'XTR'
}

export interface AppError {
  message: string
  status?: number
}
