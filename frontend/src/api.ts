export type Highlight = { episode: string; start: number; end: number; note: string }
export type Drama = {
  id: number; title: string; theater:string; description:string; genres: string[]; actor_names: string[]; source_note: string
  is_ai_generated: boolean;is_dubbed_content:boolean; episode_count: number; episodes: string[]; stills: string[]; highlights: Highlight[]; file_dir:string
  language:string;promotion_episode_count:number;total_episode_count:number;generated_files:GeneratedFile[]
  cover_vertical_path:string;cover_square_path:string;cover_horizontal_path:string
  source_files:{name:string;size_bytes:number}[];source_size_bytes:number;source_storage:'server'|'local';source_storage_path:string
}
export type GeneratedFile = { name:string;size:number;created_at:string }
export type ScanLog = { path: string; status: string; message: string }
export type Clip = {
  id: number; drama_id: number; template_name: string; source_eps: string[]; source_start: number; source_end: number; duration: number
  file_path: string; subtitle_text: string; status: string; preview_image: string
  audio_replaced: boolean; progress: number; current_step: string; error_message: string
  hit_words: string[]; review_note: string; reviewed_at: string | null; error_advice: string
  hook_asset_id:number|null;factory_job_id:number|null;asset_kind:string
}
export type TextPart = { text: string; hit: boolean }
export type ModerationResult = { hit_words: string[]; safe: boolean; highlighted_title: TextPart[]; highlighted_caption: TextPart[] }
export type TitleCandidate = { formula: number; title: string; caption: string; hashtags: string[]; hit_words: string[] }
export type Post = { id: number; clip_id: number; title: string; caption: string; hashtags: string[]; cover_path_169: string; cover_path_916: string; cover_fallback: boolean }
export type Account = { id: number; platform: string; name: string; account_type: string; is_new: boolean; status: string; strategy_id: number | null; platform_user_id:string;avatar_url:string;profile_url:string;follower_count:number;last_checked_at:string|null;connected_at:string|null;last_error:string;capabilities:string[];configured:boolean;credential_status:Record<string,string|boolean|number> }
export type AccountStrategy = {
  id:number;name:string;history_text:string;builtin:boolean;confirmed:boolean
  positioning?:string;persona_keywords?:string[];tone_examples?:string;daily_posts?:number;posting_times?:string[];tag_pool?:string[];default_clip_template?:string;title_formula_preference?:number
}
export type ContentExample = { id:number; content:string; genres:string[]; language:string; platform:string; enabled:boolean }
export type TagLibraryItem = { id:number; tag:string; genres:string[]; language:string; platform:string; enabled:boolean }
export type HookSuggestion = { id:number; drama_id:number; episode:string; start:number; end:number; score:number; reasons:string[]; status:string }
export type EmotionWord = { id:number; word:string; enabled:boolean }
export type VisualReview = { id:number; clip_id:number; risk:'green'|'yellow'|'red'; reasons:string[]; status:string; provider:string; image_path:string; created_at:string }
export type HotNote = { id:number; content:string; platform:string; expires_at:string; created_at:string }
export type PublishJob = { id: number; post_id: number; account_id: number; scheduled_at: string; channel: string; status: string; ai_disclosure: boolean; result_log: string; platform_video_id: string; retry_count: number;publish_options:Record<string,unknown>;platform_url:string;status_checked_at:string|null;submitted_at:string|null;completed_at:string|null }
export type PlatformMedia = { id:string;title:string;published_at:string|null;scheduled_at?:string|null;local_scheduled_at?:string|null;calendar_at?:string|null;time_source?:'scheduled'|'published'|'';publication_status?:string;event_status?:string;job_id?:number;views:number;likes:number;comments:number;url:string;thumbnail_url:string;duration_seconds:number|null;impressions:number|null;clicks:number|null;ctr:number|null;watch_time_seconds:number|null;estimated_revenue:number|null;rpm:number|null;subscribers_gained:number|null }
export type AccountInsightPoint = { date:string;views:number;watch_time_seconds:number;average_view_duration_seconds:number|null;impressions:number|null;ctr:number|null;estimated_revenue:number|null;subscribers_gained:number;subscribers_lost:number }
export type AccountInsights = { account_id:number;platform:string;range:{preset:'all'|string;days:number;start:string;end:string};source:string;series_mode:'daily_activity'|'published_content_totals';totals:{views:number|null;channel_views:number|null;impressions:number|null;ctr:number|null;watch_time_seconds:number|null;average_view_duration_seconds:number|null;estimated_revenue:number|null;rpm:number|null;subscribers_gained:number|null;subscribers_lost:number|null;followers:number;video_count:number|null};series:AccountInsightPoint[];unavailable:string[] }
export type Metric = { id: number; date: string; views: number; likes: number; comments: number; followers:number; impressions:number|null;clicks:number|null;ctr:number|null;watch_time_seconds:number|null;estimated_revenue:number|null;rpm:number|null;subscribers_gained:number|null; post_title: string; account_name: string; account_type: string; cover_fallback: boolean; clip_id: number | null }
export type Dashboard = { account_trends:{account:string;date:string;views:number;followers:number}[]; templates:{template:string;avg_views:number;count:number}[]; dramas:{drama:string;total_views:number;best_views:number}[]; covers:{kind:string;avg_views:number;avg_likes:number;count:number}[] }
export type AccountMatrixRow = { id:number;platform:string;name:string;account_type:string;status:string;strategy_id:number|null;posts_7d:number;published_total:number;failed_total:number;views_7d:number;likes_7d:number;comments_7d:number;views_total:number;impressions:number|null;clicks:number|null;ctr:number|null;watch_time_seconds:number|null;estimated_revenue:number|null;rpm:number|null;subscribers_gained:number|null;followers:number;last_publish_at:string|null;last_error?:string;last_checked_at?:string|null;avatar_url?:string;profile_url?:string;capabilities?:string[];configured?:boolean }
export type WorkspaceSummary = { kpis:{accounts:number;connected_accounts:number;dramas:number;ready_posts:number;scheduled_jobs:number;views_7d:number;comments_7d:number};workflow:{source:number;processing:number;review:number;ready:number;published:number};alerts:{failed_jobs:number;visual_risk:number;comment_tickets:number};matrix:AccountMatrixRow[];generated_at:string }
export type MetaSFSInput = { drama_id:number;series_slug:string;description:string;locale:string;genres:string[];release_date:string;cast_list:string[];tags:string[];geogating:string[];ai_content:boolean;dubbed_content:boolean;include_episode_csv:boolean;include_thumbnails:boolean;local_destination_token?:string }
export type MetaPreflight = { ready:boolean;series_slug:string;episode_count:number;source_mode:'factory_meta_split'|'source_episodes';assets:{episode:number;source:string;target:string;info:Record<string,number|string|boolean>;issues:string[]}[];cover_source:{path:string;width:number;height:number};cover_sources:Record<'vertical'|'square'|'horizontal',{path:string;width:number;height:number}>;blockers:string[];automatic_fixes:string[];requirements:Record<string,string> }
export type MetaFactorySource = { ready:boolean;episode_count:number;source_episode_count:number;files:string[] }
export type MetaPackage = { id:number;drama_id:number;series_slug:string;output_dir:string;status:string;validation_json:Record<string,unknown>;drive_folder_id:string;drive_folder_url:string;last_error:string;uploaded_at:string|null;created_at:string }
export type MetaPackageFiles = { folder_name:string;total_bytes:number;files:{path:string;size:number}[] }
export type SocialComment = { id:number;external_id:string;platform:string;account_id:number|null;video_id:string;video_title:string;video_url:string;author_name:string;author_handle:string;text_original:string;text_zh:string;like_count:number;published_at:string|null;sentiment:string;user_status:string;keyword_category:string;keywords:string[];summary:string;ticket_type:string;severity:string;needs_human:boolean;status:string;suggested_replies:string[];analysis_source:string;reply_id:string;reply_text:string;replied_at:string|null;fetched_at:string }
export type EngagementSummary = { total:number;analyzed:number;pending:number;needs_human:number;high_risk:number;buyer_intent:number;sentiment:{positive:number;negative:number;neutral:number};health:'healthy'|'watch'|'urgent' }
export type ScriptSegment = { start:number;end:number;text:string;energy_score:number;energy_reasons:string[];high_energy:boolean;sensitive:Record<string,string[]>;confidence?:number;overall_risk_score?:number;risk_scores?:{body_focus?:number;action?:number;dialogue_context?:number;expression_audio?:number;scene_context?:number};review_status?:'not_applicable'|'pending'|'approved'|'rejected';evidence?:string[];frame_files?:string[];source?:string }
export type EpisodeAnalysis = { episode:string;duration:number;segment_count:number;segments:ScriptSegment[];high_energy:ScriptSegment[];sensitive:ScriptSegment[];summary?:string }
export type FactoryAnalysis = { status:'not_analyzed'|'queued'|'processing'|'completed'|'failed';progress:number;current_step:string;error_message:string;drama_id:number;title:string;source?:string;provider?:string;model?:string;configured_provider?:string;configured_model?:string;ai_ready?:boolean;requires_reanalysis?:boolean;is_active?:boolean;generated_at?:string;updated_at?:string;resume_count?:number;episode_count:number;total_duration:number;segment_count:number;high_energy_count:number;sensitive_count:number;sampled_frame_count:number;api_call_count:number;episodes:EpisodeAnalysis[] }
export type FactoryOutputMode = 'clean_full'|'hook_variants'|'meta_split'
export type FactoryJob = { id:number;drama_id:number;status:'queued'|'processing'|'completed'|'failed';current_step:string;progress:number;max_duration_seconds:number;hook_duration_seconds:number;publish_variant_count:number;remove_sensitive:boolean;compression_profile:string;output_modes:FactoryOutputMode[];hooks_per_variant:number;selected_hook_ids:number[];source_files:string[];clean_count:number;publish_count:number;meta_count:number;total_duration:number;removed_seconds:number;output_bytes:number;output_dir:string;warnings:string[];error_message:string;created_at:string;started_at:string|null;completed_at:string|null }
export type GeneratedAsset = { id:number;factory_job_id:number;drama_id:number;kind:'clean_full'|'hook_full'|'meta_episode';sequence:number;filename:string;duration:number;size_bytes:number;hook_asset_id:number|null;hook_asset_ids:number[];clip_id:number|null;created_at:string }
export type HookAsset = { id:number;drama_id:number;drama_title:string;episode:string;start:number;end:number;note:string;source:string;energy_score:number;active:boolean;use_count:number;published_count:number;views:number;likes:number;comments:number;heat_score:number;last_used_at:string|null;preview_ready:boolean }
export type IntegrationConfig = {vault_ready:boolean;public_media_ready:boolean;callbacks:Record<'youtube'|'meta'|'tiktok',string>;apps:Record<'youtube'|'meta'|'tiktok',{client_id:string;client_secret_set:boolean;updated_at:string|null}>}
export type TikTokCreatorInfo = {privacy_level_options:string[];comment_disabled:boolean;duet_disabled:boolean;stitch_disabled:boolean;max_video_post_duration_sec:number}
export type AuthUser = {id:number;email:string;is_developer:boolean;email_verified:boolean;created_at:string;last_login_at:string|null}
export type CloudAsset = {id:number;drama_id:number;drama_title:string;uploader_email:string;kind:string;filename:string;size_bytes:number;duration:number;download_count:number;storage_backend:string;created_at:string}
export type AdminAnalytics = {range_days:number;totals:{users:number;active_users:number;api_calls:number;model_calls:number;tokens:number;cloud_assets:number;cloud_bytes:number};users:{user_id:number;email:string;api_calls:number;model_calls:number;input_tokens:number;output_tokens:number;total_tokens:number;feature_actions:number;failures:number}[];features:{feature:string;uses:number;successes:number;failures:number;cache_hits:number;model_calls:number;tokens:number;active_users:number;usage_rate:number;success_rate:number|null;hit_rate:number|null}[];daily:{date:string;api_calls:number;model_calls:number;tokens:number;success:number;failure:number}[];definitions:Record<string,string>}

async function responseError(response: Response, fallback='请求失败') {
  try {
    const payload = await response.json()
    const detail = payload?.detail
    if (Array.isArray(detail)) return detail.map(item=>item?.msg||item?.message||String(item)).join('；')
    if (typeof detail === 'string') return detail
    if (detail) return JSON.stringify(detail)
  } catch { /* 响应不是 JSON 时使用后备提示 */ }
  return fallback
}

type RequestOptions = RequestInit & { cacheTtlMs?:number; forceRefresh?:boolean; cacheKey?:string }
type CachedResponse = { expiresAt:number; value:unknown }

const responseCache = new Map<string,CachedResponse>()
const pendingRequests = new Map<string,Promise<unknown>>()

function clearResponseCache(){
  responseCache.clear()
}

async function request<T>(url: string, options?: RequestOptions): Promise<T> {
  const {cacheTtlMs=0,forceRefresh=false,cacheKey=url,...init}=options||{}
  const method=(init.method||'GET').toUpperCase()
  const cacheable=method==='GET'&&cacheTtlMs>0
  if(cacheable&&!forceRefresh){
    const cached=responseCache.get(cacheKey)
    if(cached&&cached.expiresAt>Date.now())return cached.value as T
    if(cached)responseCache.delete(cacheKey)
    const pending=pendingRequests.get(cacheKey)
    if(pending)return pending as Promise<T>
  }
  const task=(async()=>{
    const response = await fetch(url, { credentials:'same-origin', headers: { 'Content-Type': 'application/json' }, ...init })
    if (!response.ok) {
      if(response.status===401&&!url.startsWith('/api/auth/'))window.dispatchEvent(new CustomEvent('jushu:unauthorized'))
      throw new Error(await responseError(response))
    }
    const value=await response.json() as T
    if(cacheable)responseCache.set(cacheKey,{expiresAt:Date.now()+cacheTtlMs,value})
    else if(method!=='GET')clearResponseCache()
    return value
  })()
  if(cacheable&&!forceRefresh)pendingRequests.set(cacheKey,task)
  try{return await task}finally{if(pendingRequests.get(cacheKey)===task)pendingRequests.delete(cacheKey)}
}

export const api = {
  authMe: () => request<{user:AuthUser;email_delivery_configured:boolean}>('/api/auth/me'),
  login: (email:string,password:string) => request<{user:AuthUser}>('/api/auth/login',{method:'POST',body:JSON.stringify({email,password})}),
  register: (email:string,password:string) => request<{user:AuthUser}>('/api/auth/register',{method:'POST',body:JSON.stringify({email,password})}),
  logout: () => request<{logged_out:boolean}>('/api/auth/logout',{method:'POST'}),
  adminAnalytics: (days=30) => request<AdminAnalytics>(`/api/admin/analytics?days=${days}`),
  sendTelemetry: (events:{client_event_id:string;feature:string;success:boolean;duration_ms:number;details:Record<string,unknown>}[]) => request<{accepted:number}>('/api/telemetry/events',{method:'POST',body:JSON.stringify({events})}),
  list: (refresh=false) => request<Drama[]>('/api/dramas',{cacheTtlMs:60_000,forceRefresh:refresh}),
  createDramaTask: (body:{title:string;theater:string;description:string;total_episode_count:number;genres:string[];language:string;is_ai_generated:boolean;is_dubbed_content:boolean}) => request<Drama>('/api/dramas',{method:'POST',body:JSON.stringify(body)}),
  scan: () => request<{ scan_root: string; logs: ScanLog[]; dramas: Drama[] }>('/api/dramas/scan', { method: 'POST' }),
  get: (id: string) => request<Drama>(`/api/dramas/${id}`),
  update: (id: number, body: object) => request<Drama>(`/api/dramas/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteDramaSources: (id:number,filename?:string) => request<Drama>(`/api/dramas/${id}/source-files${filename?`?filename=${encodeURIComponent(filename)}`:''}`,{method:'DELETE'}),
  highlights: (id: number, highlights: Highlight[]) => request<Drama>(`/api/dramas/${id}/highlights`, { method: 'PUT', body: JSON.stringify({ highlights }) }),
  clips: (dramaId?: number,refresh=false) => request<Clip[]>(`/api/clips${dramaId ? `?drama_id=${dramaId}` : ''}`,{cacheTtlMs:30_000,forceRefresh:refresh}),
  createClips: (dramaId: number, templateName = 'suspense_hook') => request<Clip[]>('/api/clips/batch', { method: 'POST', body: JSON.stringify({ drama_id: dramaId, template_name: templateName }) }),
  reviewClip: (clipId: number, status: 'approved' | 'blocked', note = '') => request<Clip>(`/api/moderation/clips/${clipId}/review`, { method: 'PUT', body: JSON.stringify({ status, note }) }),
  moderateText: (title: string, caption: string) => request<ModerationResult>('/api/moderation/text', { method: 'POST', body: JSON.stringify({ title, caption }) }),
  moderationConfig: () => request<{ cover_reminder: string }>('/api/moderation/config'),
  generateTitles: (clipId: number, accountType: string, targetLanguage: string, formula: number | 'auto', accountId?: number, hotTags:string[] = [], strategy?:AccountStrategy, includeTheaterTag=true) => request<{ candidates: TitleCandidate[]; degraded: boolean; provider: string; context_used: string[] }>('/api/creative/titles', { method: 'POST', body: JSON.stringify({ clip_id: clipId, account_type: accountType, target_language: targetLanguage, formula, account_id: accountId, strategy, hot_tags:hotTags, include_theater_tag:includeTheaterTag }) }),
  createPost: (clipId: number, accountType: string, candidate: TitleCandidate) => request<Post>('/api/creative/posts', { method: 'POST', body: JSON.stringify({ clip_id: clipId, account_type: accountType, candidate }) }),
  posts: (refresh=false) => request<Post[]>('/api/creative/posts',{cacheTtlMs:30_000,forceRefresh:refresh}),
  accounts: (refresh=false) => request<Account[]>('/api/publish/accounts',{cacheTtlMs:30_000,forceRefresh:refresh}),
  createAccount: (body: object) => request<Account>('/api/publish/accounts', { method: 'POST', body: JSON.stringify(body) }),
  configureAccount: (body:object,accountId?:number) => request<Account>(`/api/publish/accounts/configure${accountId?`?account_id=${accountId}`:''}`,{method:'POST',body:JSON.stringify(body)}),
  checkAccount: (id:number) => request<Account>(`/api/publish/accounts/${id}/check`,{method:'POST'}),
  removeAccount: (id:number) => request<{removed:boolean;account_id:number;history_preserved:boolean}>(`/api/publish/accounts/${id}`,{method:'DELETE'}),
  accountMedia: (id:number,limit=50,refresh=false) => {const key=`/api/publish/accounts/${id}/media?limit=${limit}`;return request<PlatformMedia[]>(`${key}${refresh?'&refresh=true':''}`,{cacheTtlMs:300_000,forceRefresh:refresh,cacheKey:key})},
  accountCalendar: (id:number,limit=50,refresh=false) => {const key=`/api/publish/accounts/${id}/calendar?limit=${limit}`;return request<PlatformMedia[]>(`${key}${refresh?'&refresh=true':''}`,{cacheTtlMs:300_000,forceRefresh:refresh,cacheKey:key})},
  accountInsights: (id:number,days:string|number='all',refresh=false) => {const key=`/api/publish/accounts/${id}/insights?days=${days}`;return request<AccountInsights>(`${key}${refresh?'&refresh=true':''}`,{cacheTtlMs:300_000,forceRefresh:refresh,cacheKey:key})},
  creatorInfo: (id:number) => request<TikTokCreatorInfo>(`/api/publish/accounts/${id}/creator-info`),
  integrationConfig: (refresh=false) => request<IntegrationConfig>('/api/integrations/config',{cacheTtlMs:60_000,forceRefresh:refresh}),
  saveIntegrationConfig: (platform:'youtube'|'meta'|'tiktok',body:object) => request(`/api/integrations/config/${platform}`,{method:'PUT',body:JSON.stringify(body)}),
  startOAuth: (platform:'youtube'|'meta'|'tiktok') => request<{authorization_url:string;expires_in:number}>(`/api/integrations/oauth/${platform}/start`,{method:'POST'}),
  strategies: () => request<AccountStrategy[]>('/api/publish/strategies'),
  createStrategy: (body: object) => request<AccountStrategy>('/api/publish/strategies', { method: 'POST', body: JSON.stringify(body) }),
  updateStrategy: (id: number, body: object) => request<AccountStrategy>(`/api/publish/strategies/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  summarizeStrategy: (name: string, historyText: string) => request<{ degraded: boolean; strategy: Omit<AccountStrategy, 'id'|'builtin'> }>('/api/publish/strategies/summarize', { method: 'POST', body: JSON.stringify({ name, history_text: historyText }) }),
  bindStrategy: (accountId: number, strategyId: number) => request<Account>(`/api/publish/accounts/${accountId}?strategy_id=${strategyId}`, { method: 'PUT' }),
  planSevenDays: (accountId: number, postIds: number[]) => request<PublishJob[]>(`/api/publish/accounts/${accountId}/plan-seven-days`, { method: 'POST', body: JSON.stringify(postIds) }),
  examples: () => request<ContentExample[]>('/api/library/examples'),
  createExample: (body: object) => request<ContentExample>('/api/library/examples', { method:'POST', body:JSON.stringify(body) }),
  updateExample: (id:number, body:object) => request<ContentExample>(`/api/library/examples/${id}`, { method:'PUT', body:JSON.stringify(body) }),
  deleteExample: (id:number) => request<{deleted:number}>(`/api/library/examples/${id}`, { method:'DELETE' }),
  batchExamples: (body:object) => request<ContentExample[]>('/api/library/examples/batch', { method:'POST', body:JSON.stringify(body) }),
  tags: () => request<TagLibraryItem[]>('/api/library/tags'),
  createTag: (body:object) => request<TagLibraryItem>('/api/library/tags', { method:'POST', body:JSON.stringify(body) }),
  updateTag: (id:number, body:object) => request<TagLibraryItem>(`/api/library/tags/${id}`, { method:'PUT', body:JSON.stringify(body) }),
  deleteTag: (id:number) => request<{deleted:number}>(`/api/library/tags/${id}`, { method:'DELETE' }),
  hookSuggestions: (dramaId:number) => request<HookSuggestion[]>(`/api/hooks/${dramaId}`),
  analyzeHooks: (dramaId:number) => request<HookSuggestion[]>(`/api/hooks/${dramaId}/analyze`, { method:'POST' }),
  decideHook: (id:number, action:'adopt'|'ignore') => request<HookSuggestion>(`/api/hooks/suggestions/${id}/${action}`, { method:'POST' }),
  emotionWords: () => request<EmotionWord[]>('/api/hooks/words'),
  addEmotionWord: (word:string) => request<EmotionWord>(`/api/hooks/words?word=${encodeURIComponent(word)}`, { method:'POST' }),
  toggleEmotionWord: (id:number, enabled:boolean) => request<EmotionWord>(`/api/hooks/words/${id}?enabled=${enabled}`, { method:'PUT' }),
  visualReviews: () => request<VisualReview[]>('/api/moderation/visual'),
  scanVisual: (clipId:number, imagePath='') => request<VisualReview>(`/api/moderation/visual/${clipId}${imagePath?`?image_path=${encodeURIComponent(imagePath)}`:''}`, {method:'POST'}),
  decideVisual: (id:number,status:'approved'|'blocked') => request<VisualReview>(`/api/moderation/visual/${id}?status=${status}`, {method:'PUT'}),
  visualQuota: () => request<{used:number;limit:number}>('/api/moderation/visual/quota'),
  hotNotes: (activeOnly=false,platform='') => request<HotNote[]>(`/api/hot-notes?active_only=${activeOnly}&platform=${platform}`),
  createHotNote: (body:object) => request<HotNote>('/api/hot-notes',{method:'POST',body:JSON.stringify(body)}),
  updateHotNote: (id:number,body:object) => request<HotNote>(`/api/hot-notes/${id}`,{method:'PUT',body:JSON.stringify(body)}),
  deleteHotNote: (id:number) => request<{deleted:number}>(`/api/hot-notes/${id}`,{method:'DELETE'}),
  publishJobs: (refresh=false) => request<PublishJob[]>('/api/publish/jobs',{cacheTtlMs:15_000,forceRefresh:refresh}),
  createPublishJob: (postId: number, accountId: number, scheduledAt: string, aiDisclosure: boolean) => request<PublishJob>('/api/publish/jobs', { method: 'POST', body: JSON.stringify({ post_id: postId, account_id: accountId, scheduled_at: scheduledAt, ai_disclosure: aiDisclosure }) }),
  runPublishJob: (id: number) => request<PublishJob>(`/api/publish/jobs/${id}/run`, { method: 'POST' }),
  metrics: () => request<Metric[]>('/api/metrics'),
  collectMetrics: (refreshExisting=false) => request<{ created: number; updated:number; skipped:number; errors:{job_id:number;account:string;error:string}[] }>(`/api/metrics/collect?refresh_existing=${refreshExisting}`, { method: 'POST' }),
  dashboard: (start?:string,end?:string) => request<Dashboard>(`/api/metrics/dashboard${start&&end?`?start=${start}&end=${end}`:''}`),
  workspaceSummary: () => request<WorkspaceSummary>('/api/workspace/summary'),
  factoryAnalysis: (dramaId:number) => request<FactoryAnalysis>(`/api/factory/${dramaId}/analysis`),
  analyzeFactory: (dramaId:number) => request<FactoryAnalysis>(`/api/factory/${dramaId}/analyze`,{method:'POST'}),
  reviewFactoryAnalysis: (dramaId:number,body:{episode:string;kind:'high_energy'|'sensitive';start:number;end:number;decision:'approved'|'rejected'|'pending';new_start?:number;new_end?:number}) => request<FactoryAnalysis>(`/api/factory/${dramaId}/analysis/review`,{method:'PATCH',body:JSON.stringify(body)}),
  factoryFrameUrl: (dramaId:number,filename:string) => `/api/factory/${dramaId}/analysis/frames/${encodeURIComponent(filename)}`,
  startFactoryProcessing: (dramaId:number,body:{max_duration_seconds:number;hook_duration_seconds:number;publish_variant_count:number;remove_sensitive:boolean;compression_profile:'balanced'|'small';output_modes:FactoryOutputMode[];hooks_per_variant:number;hook_ids:number[]}) => request<FactoryJob>(`/api/factory/${dramaId}/process`,{method:'POST',body:JSON.stringify(body)}),
  factoryJobs: (dramaId:number) => request<FactoryJob[]>(`/api/factory/${dramaId}/jobs`),
  factoryAssets: (dramaId:number) => request<GeneratedAsset[]>(`/api/factory/${dramaId}/assets`),
  uploadCloudAsset: (assetId:number) => request<CloudAsset>(`/api/factory/assets/${assetId}/cloud`,{method:'POST'}),
  cloudAssets: (refresh=false) => request<CloudAsset[]>('/api/factory/cloud-assets',{cacheTtlMs:60_000,forceRefresh:refresh}),
  factoryHooks: (dramaId?:number,activeOnly=false) => request<HookAsset[]>(`/api/factory/hooks${dramaId?`?drama_id=${dramaId}&active_only=${activeOnly}`:`?active_only=${activeOnly}`}`),
  syncFactoryHooks: (dramaId:number) => request<HookAsset[]>(`/api/factory/${dramaId}/hooks/sync`,{method:'POST'}),
  setFactoryHookActive: (hookId:number,active:boolean) => request<HookAsset>(`/api/factory/hooks/${hookId}?active=${active}`,{method:'PATCH'}),
  accountMatrix: (refresh=false) => request<AccountMatrixRow[]>('/api/workspace/account-matrix',{cacheTtlMs:30_000,forceRefresh:refresh}),
  metaFactorySource: (dramaId:number) => request<MetaFactorySource>(`/api/meta-sfs/source/${dramaId}`),
  selectMetaOutputDirectory: () => request<{token:string;name:string}>('/api/meta-sfs/select-local-directory',{method:'POST'}),
  metaPreflight: (body:MetaSFSInput) => request<MetaPreflight>('/api/meta-sfs/preflight',{method:'POST',body:JSON.stringify(body)}),
  buildMetaPackage: (body:MetaSFSInput) => request<MetaPackage>('/api/meta-sfs/build',{method:'POST',body:JSON.stringify(body)}),
  metaPackages: () => request<MetaPackage[]>('/api/meta-sfs/packages'),
  metaPackageFiles: (id:number) => request<MetaPackageFiles>(`/api/meta-sfs/packages/${id}/files`),
  metaPackageFileUrl: (id:number,path:string) => `/api/meta-sfs/packages/${id}/files/${path.split('/').map(encodeURIComponent).join('/')}`,
  metaPackageArchiveUrl: (id:number) => `/api/meta-sfs/packages/${id}/archive`,
  openMetaPackageFolder: (id:number) => request<{opened:boolean;path:string}>(`/api/meta-sfs/packages/${id}/open-folder`,{method:'POST'}),
  copyMetaPackageLocal: (id:number,token:string) => request<{path:string;folder_name:string}>(`/api/meta-sfs/packages/${id}/copy-local?token=${encodeURIComponent(token)}`,{method:'POST'}),
  uploadMetaPackage: (id:number) => request<MetaPackage>(`/api/meta-sfs/packages/${id}/upload-drive`,{method:'POST'}),
  engagementSummary: () => request<EngagementSummary>('/api/engagement/summary'),
  socialComments: (filters='',refresh=false) => request<SocialComment[]>(`/api/engagement/comments${filters}`,{cacheTtlMs:30_000,forceRefresh:refresh}),
  importComments: (items:object[]) => request<{created:number;updated:number}>('/api/engagement/comments/import',{method:'POST',body:JSON.stringify({items})}),
  analyzeComments: (commentIds:number[],useAi=false) => request<{analyzed:number;source:string;items:SocialComment[]}>('/api/engagement/comments/analyze',{method:'POST',body:JSON.stringify({comment_ids:commentIds,use_ai:useAi})}),
  setCommentStatus: (id:number,status:string) => request<SocialComment>(`/api/engagement/comments/${id}`,{method:'PATCH',body:JSON.stringify({status})}),
  syncComments: (accountIds:number[]=[],maxComments=100) => request<{created:number;updated:number;accounts:object[];errors:object[]}>('/api/engagement/sync',{method:'POST',body:JSON.stringify({account_ids:accountIds,max_comments:maxComments})}),
  replyComment: (id:number,reply:string) => request<SocialComment>(`/api/engagement/comments/${id}/reply`,{method:'POST',body:JSON.stringify({message:reply})}),
  syncYouTube: (accountIds:number[]=[],maxVideos=10) => request<{created:number;updated:number;videos_processed:number}>('/api/engagement/sync-youtube',{method:'POST',body:JSON.stringify({account_ids:accountIds,max_videos:maxVideos})}),
  batchPublish: (postIds:number[],accountIds:number[],scheduledAt:string,runNow=false,aiDisclosure=false,publishOptions:Record<string,unknown>={}) => request<PublishJob[]>('/api/publish/jobs/batch',{method:'POST',body:JSON.stringify({post_ids:postIds,account_ids:accountIds,scheduled_at:scheduledAt,run_now:runNow,ai_disclosure:aiDisclosure,publish_options:publishOptions})}),
  refreshPublishJob: (id:number) => request<PublishJob>(`/api/publish/jobs/${id}/refresh`,{method:'POST'}),
  registerDrama: (title: string, theater:string, absolutePath: string, sourceNote: string) => request<Drama>('/api/dramas/register', { method: 'POST', body: JSON.stringify({ title, theater, absolute_path: absolutePath, source_note: sourceNote }) }),
  uploadVideo: async (dramaTitle: string, sourceNote: string, file: File, onProgress: (value: number) => void, destination:'episodes'|'stills'|'publish'|'cover_vertical'|'cover_square'|'cover_horizontal'='episodes') => {
    if(!file.size)throw new Error('不能上传空文件')
    const chunkSize = 8 * 1024 * 1024; const totalChunks = Math.ceil(file.size / chunkSize); const concurrency = 4
    const init = await request<{ upload_id: string; received_chunks: number[] }>('/api/dramas/uploads/init', { method: 'POST', body: JSON.stringify({ drama_title: dramaTitle, filename: file.name, total_size: file.size, total_chunks: totalChunks, source_note: sourceNote, destination }) })
    const received = new Set(init.received_chunks)
    const chunkBytes=(index:number)=>Math.min(file.size,(index+1)*chunkSize)-index*chunkSize
    let uploadedBytes=[...received].reduce((sum,index)=>sum+chunkBytes(index),0);onProgress(Math.round(uploadedBytes/file.size*100))
    const pending=Array.from({length:totalChunks},(_,index)=>index).filter(index=>!received.has(index));let cursor=0
    const uploadChunk=async(index:number)=>{
      let failure:Error|undefined
      for(let attempt=0;attempt<3;attempt++){
        try{
          const response=await fetch(`/api/dramas/uploads/${init.upload_id}/chunks/${index}`,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:file.slice(index*chunkSize,Math.min(file.size,(index+1)*chunkSize))})
          if(!response.ok)throw new Error(await responseError(response,`分片 ${index+1} 上传失败`))
          return
        }catch(error){failure=error as Error;if(attempt<2)await new Promise(resolve=>window.setTimeout(resolve,600*2**attempt))}
      }
      throw failure??new Error(`分片 ${index+1} 上传失败`)
    }
    const worker=async()=>{while(cursor<pending.length){const index=pending[cursor++];await uploadChunk(index);uploadedBytes+=chunkBytes(index);onProgress(Math.round(uploadedBytes/file.size*100))}}
    await Promise.all(Array.from({length:Math.min(concurrency,pending.length)},()=>worker()))
    return request<Drama>(`/api/dramas/uploads/${init.upload_id}/complete`, { method: 'POST' })
  },
}
