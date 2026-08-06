export type Highlight = { episode: string; start: number; end: number; note: string }
export type Drama = {
  id: number; title: string; genres: string[]; actor_names: string[]; source_note: string
  is_ai_generated: boolean; episode_count: number; episodes: string[]; stills: string[]; highlights: Highlight[]; file_dir:string
}
export type ScanLog = { path: string; status: string; message: string }
export type Clip = {
  id: number; drama_id: number; template_name: string; source_eps: string[]; source_start: number; source_end: number; duration: number
  file_path: string; subtitle_text: string; status: string; preview_image: string
  audio_replaced: boolean; progress: number; current_step: string; error_message: string
  hit_words: string[]; review_note: string; reviewed_at: string | null; error_advice: string
}
export type TextPart = { text: string; hit: boolean }
export type ModerationResult = { hit_words: string[]; safe: boolean; highlighted_title: TextPart[]; highlighted_caption: TextPart[] }
export type TitleCandidate = { formula: number; title: string; caption: string; hashtags: string[]; hit_words: string[] }
export type Basemap = { id: number; drama_id: number; file_path: string; source: string; status: string }
export type Post = { id: number; clip_id: number; title: string; caption: string; hashtags: string[]; cover_path_169: string; cover_path_916: string; cover_fallback: boolean }
export type Account = { id: number; platform: string; name: string; account_type: string; is_new: boolean; status: string; strategy_id: number | null; platform_user_id:string;avatar_url:string;profile_url:string;follower_count:number;last_checked_at:string|null;connected_at:string|null;last_error:string;capabilities:string[];configured:boolean;credential_status:Record<string,string|boolean|number> }
export type AccountStrategy = { id: number; name: string; positioning: string; persona_keywords: string[]; tone_examples: string; daily_posts: number; posting_times: string[]; tag_pool: string[]; default_clip_template: string; title_formula_preference: number; builtin: boolean; confirmed: boolean }
export type ContentExample = { id:number; content:string; genres:string[]; language:string; platform:string; enabled:boolean }
export type TagLibraryItem = { id:number; tag:string; genres:string[]; language:string; platform:string; enabled:boolean }
export type HookSuggestion = { id:number; drama_id:number; episode:string; start:number; end:number; score:number; reasons:string[]; status:string }
export type EmotionWord = { id:number; word:string; enabled:boolean }
export type VisualReview = { id:number; clip_id:number; risk:'green'|'yellow'|'red'; reasons:string[]; status:string; provider:string; image_path:string; created_at:string }
export type HotNote = { id:number; content:string; platform:string; expires_at:string; created_at:string }
export type PublishJob = { id: number; post_id: number; account_id: number; scheduled_at: string; channel: string; status: string; ai_disclosure: boolean; result_log: string; platform_video_id: string; retry_count: number;publish_options:Record<string,unknown>;platform_url:string;status_checked_at:string|null;submitted_at:string|null;completed_at:string|null }
export type PlatformMedia = { id:string;title:string;published_at:string|null;views:number;likes:number;comments:number;url:string;thumbnail_url:string;duration_seconds:number|null;impressions:number|null;clicks:number|null;ctr:number|null;watch_time_seconds:number|null;estimated_revenue:number|null;rpm:number|null;subscribers_gained:number|null }
export type Metric = { id: number; date: string; views: number; likes: number; comments: number; followers:number; impressions:number|null;clicks:number|null;ctr:number|null;watch_time_seconds:number|null;estimated_revenue:number|null;rpm:number|null;subscribers_gained:number|null; post_title: string; account_name: string; account_type: string; cover_fallback: boolean; clip_id: number | null }
export type Dashboard = { account_trends:{account:string;date:string;views:number;followers:number}[]; templates:{template:string;avg_views:number;count:number}[]; dramas:{drama:string;total_views:number;best_views:number}[]; covers:{kind:string;avg_views:number;avg_likes:number;count:number}[] }
export type AccountMatrixRow = { id:number;platform:string;name:string;account_type:string;status:string;strategy_id:number|null;posts_7d:number;published_total:number;failed_total:number;views_7d:number;likes_7d:number;comments_7d:number;views_total:number;impressions:number|null;clicks:number|null;ctr:number|null;watch_time_seconds:number|null;estimated_revenue:number|null;rpm:number|null;subscribers_gained:number|null;followers:number;last_publish_at:string|null;last_error?:string;last_checked_at?:string|null;avatar_url?:string;profile_url?:string;capabilities?:string[];configured?:boolean }
export type WorkspaceSummary = { kpis:{accounts:number;connected_accounts:number;dramas:number;ready_posts:number;scheduled_jobs:number;views_7d:number;comments_7d:number};workflow:{source:number;processing:number;review:number;ready:number;published:number};alerts:{failed_jobs:number;visual_risk:number;comment_tickets:number};matrix:AccountMatrixRow[];generated_at:string }
export type MetaSFSInput = { drama_id:number;series_slug:string;description:string;locale:string;genres:string[];release_date:string;cast_list:string[];tags:string[];geogating:string[];ai_content:boolean;dubbed_content:boolean;include_episode_csv:boolean;include_thumbnails:boolean }
export type MetaPreflight = { ready:boolean;series_slug:string;episode_count:number;assets:{episode:number;source:string;target:string;info:Record<string,number|string|boolean>;issues:string[]}[];cover_source:{path:string;width:number;height:number};blockers:string[];automatic_fixes:string[];requirements:Record<string,string> }
export type MetaPackage = { id:number;drama_id:number;series_slug:string;output_dir:string;status:string;validation_json:Record<string,unknown>;drive_folder_id:string;drive_folder_url:string;last_error:string;uploaded_at:string|null;created_at:string }
export type SocialComment = { id:number;external_id:string;platform:string;account_id:number|null;video_id:string;video_title:string;video_url:string;author_name:string;author_handle:string;text_original:string;text_zh:string;like_count:number;published_at:string|null;sentiment:string;user_status:string;keyword_category:string;keywords:string[];summary:string;ticket_type:string;severity:string;needs_human:boolean;status:string;suggested_replies:string[];analysis_source:string;reply_id:string;reply_text:string;replied_at:string|null;fetched_at:string }
export type EngagementSummary = { total:number;analyzed:number;pending:number;needs_human:number;high_risk:number;buyer_intent:number;sentiment:{positive:number;negative:number;neutral:number};health:'healthy'|'watch'|'urgent' }
export type ScriptSegment = { start:number;end:number;text:string;energy_score:number;energy_reasons:string[];high_energy:boolean;sensitive:Record<string,string[]> }
export type EpisodeAnalysis = { episode:string;duration:number;segment_count:number;segments:ScriptSegment[];high_energy:ScriptSegment[];sensitive:ScriptSegment[] }
export type FactoryAnalysis = { status:'not_analyzed'|'completed';drama_id:number;title:string;source?:string;generated_at?:string;episode_count:number;total_duration:number;segment_count:number;high_energy_count:number;sensitive_count:number;episodes:EpisodeAnalysis[] }
export type IntegrationConfig = {vault_ready:boolean;public_media_ready:boolean;callbacks:Record<'youtube'|'meta'|'tiktok',string>;apps:Record<'youtube'|'meta'|'tiktok',{client_id:string;client_secret_set:boolean;updated_at:string|null}>}
export type TikTokCreatorInfo = {privacy_level_options:string[];comment_disabled:boolean;duet_disabled:boolean;stitch_disabled:boolean;max_video_post_duration_sec:number}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) throw new Error((await response.json()).detail ?? '请求失败')
  return response.json()
}

export const api = {
  list: () => request<Drama[]>('/api/dramas'),
  scan: () => request<{ scan_root: string; logs: ScanLog[]; dramas: Drama[] }>('/api/dramas/scan', { method: 'POST' }),
  get: (id: string) => request<Drama>(`/api/dramas/${id}`),
  update: (id: number, body: object) => request<Drama>(`/api/dramas/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  highlights: (id: number, highlights: Highlight[]) => request<Drama>(`/api/dramas/${id}/highlights`, { method: 'PUT', body: JSON.stringify({ highlights }) }),
  clips: (dramaId?: number) => request<Clip[]>(`/api/clips${dramaId ? `?drama_id=${dramaId}` : ''}`),
  createClips: (dramaId: number, templateName = 'suspense_hook') => request<Clip[]>('/api/clips/batch', { method: 'POST', body: JSON.stringify({ drama_id: dramaId, template_name: templateName }) }),
  reviewClip: (clipId: number, status: 'approved' | 'blocked', note = '') => request<Clip>(`/api/moderation/clips/${clipId}/review`, { method: 'PUT', body: JSON.stringify({ status, note }) }),
  moderateText: (title: string, caption: string) => request<ModerationResult>('/api/moderation/text', { method: 'POST', body: JSON.stringify({ title, caption }) }),
  moderationConfig: () => request<{ cover_reminder: string }>('/api/moderation/config'),
  generateTitles: (clipId: number, accountType: string, targetLanguage: string, formula: number | 'auto', accountId?: number, hotTags:string[] = []) => request<{ candidates: TitleCandidate[]; degraded: boolean; provider: string; context_used: string[] }>('/api/creative/titles', { method: 'POST', body: JSON.stringify({ clip_id: clipId, account_type: accountType, target_language: targetLanguage, formula, account_id: accountId, hot_tags:hotTags }) }),
  createPost: (clipId: number, accountType: string, candidate: TitleCandidate) => request<Post>('/api/creative/posts', { method: 'POST', body: JSON.stringify({ clip_id: clipId, account_type: accountType, candidate }) }),
  basemaps: (dramaId: number) => request<Basemap[]>(`/api/creative/basemaps?drama_id=${dramaId}`),
  generateBasemaps: (dramaId: number, stillFilename: string) => request<Basemap[]>('/api/creative/basemaps', { method: 'POST', body: JSON.stringify({ drama_id: dramaId, still_filename: stillFilename }) }),
  reviewBasemap: (id: number, status: 'approved' | 'rejected') => request<Basemap>(`/api/creative/basemaps/${id}`, { method: 'PUT', body: JSON.stringify({ status }) }),
  createCovers: (postId: number, accountType: string) => request<Post>('/api/creative/covers', { method: 'POST', body: JSON.stringify({ post_id: postId, account_type: accountType }) }),
  quotas: () => request<{ month: string; basemap: { used: number; limit: number }; direct: { used: number; limit: number } }>('/api/creative/quotas'),
  posts: () => request<Post[]>('/api/creative/posts'),
  accounts: () => request<Account[]>('/api/publish/accounts'),
  createAccount: (body: object) => request<Account>('/api/publish/accounts', { method: 'POST', body: JSON.stringify(body) }),
  configureAccount: (body:object,accountId?:number) => request<Account>(`/api/publish/accounts/configure${accountId?`?account_id=${accountId}`:''}`,{method:'POST',body:JSON.stringify(body)}),
  checkAccount: (id:number) => request<Account>(`/api/publish/accounts/${id}/check`,{method:'POST'}),
  disconnectAccount: (id:number) => request<Account>(`/api/publish/accounts/${id}/disconnect`,{method:'POST'}),
  accountMedia: (id:number,limit=50) => request<PlatformMedia[]>(`/api/publish/accounts/${id}/media?limit=${limit}`),
  creatorInfo: (id:number) => request<TikTokCreatorInfo>(`/api/publish/accounts/${id}/creator-info`),
  integrationConfig: () => request<IntegrationConfig>('/api/integrations/config'),
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
  publishJobs: () => request<PublishJob[]>('/api/publish/jobs'),
  createPublishJob: (postId: number, accountId: number, scheduledAt: string, aiDisclosure: boolean) => request<PublishJob>('/api/publish/jobs', { method: 'POST', body: JSON.stringify({ post_id: postId, account_id: accountId, scheduled_at: scheduledAt, ai_disclosure: aiDisclosure }) }),
  runPublishJob: (id: number) => request<PublishJob>(`/api/publish/jobs/${id}/run`, { method: 'POST' }),
  metrics: () => request<Metric[]>('/api/metrics'),
  collectMetrics: () => request<{ created: number; skipped:number; errors:{job_id:number;account:string;error:string}[] }>('/api/metrics/collect', { method: 'POST' }),
  dashboard: (start?:string,end?:string) => request<Dashboard>(`/api/metrics/dashboard${start&&end?`?start=${start}&end=${end}`:''}`),
  workspaceSummary: () => request<WorkspaceSummary>('/api/workspace/summary'),
  factoryAnalysis: (dramaId:number) => request<FactoryAnalysis>(`/api/factory/${dramaId}/analysis`),
  analyzeFactory: (dramaId:number) => request<FactoryAnalysis>(`/api/factory/${dramaId}/analyze`,{method:'POST'}),
  accountMatrix: () => request<AccountMatrixRow[]>('/api/workspace/account-matrix'),
  metaPreflight: (body:MetaSFSInput) => request<MetaPreflight>('/api/meta-sfs/preflight',{method:'POST',body:JSON.stringify(body)}),
  buildMetaPackage: (body:MetaSFSInput) => request<MetaPackage>('/api/meta-sfs/build',{method:'POST',body:JSON.stringify(body)}),
  metaPackages: () => request<MetaPackage[]>('/api/meta-sfs/packages'),
  uploadMetaPackage: (id:number) => request<MetaPackage>(`/api/meta-sfs/packages/${id}/upload-drive`,{method:'POST'}),
  engagementSummary: () => request<EngagementSummary>('/api/engagement/summary'),
  socialComments: (filters='') => request<SocialComment[]>(`/api/engagement/comments${filters}`),
  importComments: (items:object[]) => request<{created:number;updated:number}>('/api/engagement/comments/import',{method:'POST',body:JSON.stringify({items})}),
  analyzeComments: (commentIds:number[],useAi=false) => request<{analyzed:number;source:string;items:SocialComment[]}>('/api/engagement/comments/analyze',{method:'POST',body:JSON.stringify({comment_ids:commentIds,use_ai:useAi})}),
  setCommentStatus: (id:number,status:string) => request<SocialComment>(`/api/engagement/comments/${id}`,{method:'PATCH',body:JSON.stringify({status})}),
  syncComments: (accountIds:number[]=[],maxComments=100) => request<{created:number;updated:number;accounts:object[];errors:object[]}>('/api/engagement/sync',{method:'POST',body:JSON.stringify({account_ids:accountIds,max_comments:maxComments})}),
  replyComment: (id:number,reply:string) => request<SocialComment>(`/api/engagement/comments/${id}/reply`,{method:'POST',body:JSON.stringify({message:reply})}),
  syncYouTube: (accountIds:number[]=[],maxVideos=10) => request<{created:number;updated:number;videos_processed:number}>('/api/engagement/sync-youtube',{method:'POST',body:JSON.stringify({account_ids:accountIds,max_videos:maxVideos})}),
  batchPublish: (postIds:number[],accountIds:number[],scheduledAt:string,runNow=false,aiDisclosure=false,publishOptions:Record<string,unknown>={}) => request<PublishJob[]>('/api/publish/jobs/batch',{method:'POST',body:JSON.stringify({post_ids:postIds,account_ids:accountIds,scheduled_at:scheduledAt,run_now:runNow,ai_disclosure:aiDisclosure,publish_options:publishOptions})}),
  refreshPublishJob: (id:number) => request<PublishJob>(`/api/publish/jobs/${id}/refresh`,{method:'POST'}),
  registerDrama: (title: string, absolutePath: string, sourceNote: string) => request<Drama>('/api/dramas/register', { method: 'POST', body: JSON.stringify({ title, absolute_path: absolutePath, source_note: sourceNote }) }),
  uploadVideo: async (dramaTitle: string, sourceNote: string, file: File, onProgress: (value: number) => void) => {
    const chunkSize = 8 * 1024 * 1024; const totalChunks = Math.ceil(file.size / chunkSize)
    const init = await request<{ upload_id: string; received_chunks: number[] }>('/api/dramas/uploads/init', { method: 'POST', body: JSON.stringify({ drama_title: dramaTitle, filename: file.name, total_size: file.size, total_chunks: totalChunks, source_note: sourceNote }) })
    const received = new Set(init.received_chunks)
    for (let index = 0; index < totalChunks; index++) {
      if (!received.has(index)) {
        const response = await fetch(`/api/dramas/uploads/${init.upload_id}/chunks/${index}`, { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: file.slice(index * chunkSize, Math.min(file.size, (index + 1) * chunkSize)) })
        if (!response.ok) throw new Error((await response.json()).detail ?? `分片 ${index + 1} 上传失败`)
      }
      onProgress(Math.round(((index + 1) / totalChunks) * 100))
    }
    return request<Drama>(`/api/dramas/uploads/${init.upload_id}/complete`, { method: 'POST' })
  },
}
