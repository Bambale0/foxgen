export type TaskStatus = 'pending' | 'completed' | 'failed'
export type TaskType = 'image' | 'video' | 'audio' | 'character'
export type AppMode = 'locked' | 'live'
export type ScenarioType = 'text' | 'imgtxt' | 'video' | 'avatar' | 'audio' | 'character'
export type UploadedFileType = 'image' | 'video' | 'audio'
export type WorkspacePanel =
  | 'assistant'
  | 'photo-prompt'
  | 'partners'
  | 'support'
  | 'more'

export interface PromptPreset {
  promptId?: number | null
  title: string
  prompt: string
  model?: string | null
  ratio?: string | null
  sourceFeedGenId?: number | null
  promptHidden?: boolean
  initialReferences?: UploadedFile[]
}

export interface VideoPromptPreset {
  title: string
  prompt: string
  model?: string | null
  scenario?: ScenarioType | null
  ratio?: string | null
  duration?: number | null
  sourceFeedGenId?: number | null
  promptHidden?: boolean
  initialStartImage?: UploadedFile[]
  initialPhotoReferences?: UploadedFile[]
  initialVideoReferences?: UploadedFile[]
}

export interface ImageModel {
  id: string
  label: string
  description: string
  cost: number
  ratios: string[]
  requires_reference: boolean
  max_references: number
  qualities?: string[]
  quality_costs?: Record<string, number>
  supports_nsfw_checker?: boolean
  supports_nsfw_mode?: boolean
}

export interface VideoModel {
  id: string
  label: string
  description: string
  durations: number[]
  ratios: string[]
  supports: ScenarioType[]
  costs: Record<string, number>
  quality_costs?: Record<string, number>
  grok_modes?: string[]
  grok_resolutions?: string[]
  veo_generation_types?: string[]
  veo_resolutions?: string[]
  supports_translation?: boolean
  supports_seed?: boolean
  supports_watermark?: boolean
  supports_negative_prompt?: boolean
  supports_cfg_scale?: boolean
  omni_modes?: string[]
  omni_resolutions?: string[]
  omni_audio_cost?: number
  omni_character_cost?: number
  omni_base_voices?: string[]
  supports_omni_seed?: boolean
  supports_omni_audio_ids?: boolean
  supports_omni_character_ids?: boolean
  supports_omni_character_audio_ids?: boolean
  max_image_references?: number
  max_video_references?: number
}

export interface PaymentPackage {
  id: string
  name: string
  credits: number
  price_rub: number
  price_stars?: number
  lava_offer_id?: string
  lava_currency?: string
  bonus_credits?: number
  popular?: boolean
  description?: string
}

export type PaymentProvider = 'telegram_stars' | 'yookassa' | 'lava'

export interface CreatePaymentResponse {
  ok: true
  provider: PaymentProvider
  order_id: string
  payment_id: string
  payment_url: string
  invoice_url?: string
  stars_amount?: number
  credits: number
  promo_bonus_credits?: number
  promo_code?: string
}

export interface Task {
  feed_id?: number | null
  task_id: string
  type: TaskType
  model: string
  model_label: string
  aspect_ratio: string
  status: TaskStatus
  result_url?: string | null
  result_urls?: string[]
  created_at: string
  prompt_preview: string
  cost: number
  duration?: number | null
  prompt_hidden?: boolean
  prompt_actions_allowed?: boolean
  is_public_feed?: boolean
  is_profile_visible?: boolean
  publication_scope?: 'private' | 'profile' | 'feed'
  feed_interactions_enabled?: boolean
  is_prompt_library?: boolean
  feed_prompt_visible?: boolean
  feed_references_visible?: boolean
  feed_blurred?: boolean
  is_adult_content?: boolean
}

export interface TaskDetail extends Task {
  prompt: string
  request_data?: {
    reference_images?: string[]
    v_reference_videos?: string[]
    audio_reference?: string | null
    [key: string]: unknown
  }
}

export interface BootstrapResponse {
  ok: true
  telegram_id?: number
  first_name: string
  last_name?: string
  telegram_username?: string
  photo_url?: string
  referral_code?: string
  profile_link?: string
  referral_link?: string
  channel_url?: string
  prompt_repeat_balance_rub?: number
  prompt_repeat_total_rub?: number
  bot_username?: string
  credits: number
  is_admin: boolean
  mini_app_url: string
  actions?: string[]
  payment_packages?: PaymentPackage[]
  image_models: ImageModel[]
  video_models: VideoModel[]
  recent_tasks: Task[]
  saved_references?: SavedReference[]
}

export interface TrendGenerationSettings {
  kind: 'image' | 'video'
  user_input: 'photo'
  model: string
  ratio: string
  quality?: string
  count?: number
  nsfw_checker?: boolean
  nsfw_enabled?: boolean
  scenario?: ScenarioType
  duration?: number
  grok_mode?: string
  grok_resolution?: string
  veo_generation_type?: string
  veo_translation?: boolean
  veo_resolution?: string
  veo_seed?: number | null
  veo_watermark?: string
  kling_negative_prompt?: string
  kling_cfg_scale?: number
  omni_resolution?: string
  omni_seed?: number | null
  omni_audio_ids?: string[]
  omni_character_ids?: string[]
  omni_base_voice?: string
  omni_voice_name?: string
  omni_voice_description?: string
  omni_example_dialogue?: string
  omni_character_name?: string
  omni_character_audio_ids?: string[]
}

export interface PromptItem {
  id: number
  title: string
  description: string
  prompt_text: string
  category: 'art' | 'business' | 'marketing' | 'photo' | 'video' | 'other'
  tags: string[]
  uses_count: number
  likes: number
  preview_url?: string | null
  model?: string | null
  generation_settings?: TrendGenerationSettings | null
  author_id: number
  status: 'pending' | 'approved' | 'rejected' | 'deactivated'
  reject_reason?: string | null
  ai_moderation_decision?: string | null
  created_at?: string | null
}

export interface FeedItem {
  id: number
  task_id: string
  model: string
  gen_type: 'image' | 'video'
  result_url: string
  preview_url?: string | null
  result_urls: string[]
  publication_link?: string | null
  media_unavailable?: boolean
  prompt?: string | null
  likes_count: number
  shares_count: number
  comments_count?: number
  aspect_ratio: string
  duration?: number | null
  scenario?: ScenarioType | null
  reference_images?: string[]
  reference_videos?: string[]
  references_count?: number
  references_hidden?: boolean
  author: string
  author_referral_code?: string | null
  author_photo_url?: string | null
  is_mine: boolean
  is_profile_visible?: boolean
  publication_scope?: 'private' | 'profile' | 'feed'
  feed_interactions_enabled?: boolean
  can_remove?: boolean
  can_blur?: boolean
  remixes: number
  score: number
  created_at: string
  prompt_hidden?: boolean
  prompt_actions_allowed?: boolean
  feed_prompt_visible?: boolean
  feed_references_visible?: boolean
  feed_blurred?: boolean
  is_adult_content?: boolean
}

export interface FeedDeepLink {
  item: FeedItem
  action: 'preview' | 'remix'
}

export interface FeedComment {
  id: number
  gen_id: number
  text: string
  author: string
  author_referral_code?: string | null
  is_mine: boolean
  created_at: string
}

export interface AppState {
  mode: AppMode
  isLoading: boolean
  error: string | null
  user: {
    telegramId?: number
    firstName: string
    lastName?: string
    username?: string
    photoUrl?: string
    referralCode?: string
    profileLink?: string
    referralLink?: string
    channelUrl?: string
    promptRepeatBalanceRub?: number
    promptRepeatTotalRub?: number
    botUsername?: string
    credits: number
    isAdmin: boolean
  }
  imageModels: ImageModel[]
  videoModels: VideoModel[]
  recentTasks: Task[]
  savedReferences: UploadedFile[]
  paymentPackages: PaymentPackage[]
  lastSync: Date | null
}

export interface ProfileSummary {
  referral_code: string
  first_name?: string
  last_name?: string
  username?: string
  display_name: string
  photo_url?: string | null
  profile_link?: string
  referral_link?: string
  channel_url?: string
  posts_count?: number
  likes_count?: number
  shares_count?: number
  remixes_count?: number
  is_me: boolean
}

export interface SavedReference {
  id: string
  kind: UploadedFileType
  url: string
  filename: string
  content_type?: string
  source?: string
  created_at?: string | null
  last_used_at?: string | null
}

export interface UploadedFile {
  id: string
  name: string
  url: string
  preview_url?: string
  type: UploadedFileType
  size: number
  uploading?: boolean
  saved_reference_id?: string | null
  created_at?: string | null
  source?: string
}
