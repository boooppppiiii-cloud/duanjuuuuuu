import type { Drama,FactoryAnalysis,FactoryJob,FactoryOutputMode,GeneratedAsset,MetaFactorySource,MetaPackage,MetaPackageFiles,MetaPreflight,MetaSFSInput } from './api'

export const LOCAL_WORKSPACE_ORIGIN='http://127.0.0.1:17862'

export type LocalWorkspaceFile={name:string;relative_path:string;size_bytes:number}
export type LocalWorkspace={
  drama_id:number;title:string;folder_name:string;absolute_path:string;file_count:number;total_bytes:number
  files:LocalWorkspaceFile[];covers:Record<'vertical'|'square'|'horizontal',string>;ffmpeg_ready:boolean;updated_at:string
}
export type LocalModelUsage={client_event_id:string;feature:string;success:boolean;duration_ms:number;event_kind:'model_call';provider:string;model:string;input_tokens:number;output_tokens:number;total_tokens:number;api_calls:number;details:Record<string,unknown>}

type LocalRequestOptions=RequestInit&{timeoutMs?:number}
type LoopbackRequestInit=RequestInit&{targetAddressSpace?:'loopback'}

export class LocalAssistantAccessError extends Error{
  readonly code:'browser_access_blocked'|'timeout'
  constructor(code:'browser_access_blocked'|'timeout',message:string){super(message);this.name='LocalAssistantAccessError';this.code=code}
}

async function localError(response:Response){
  try{const payload=await response.json();return typeof payload?.detail==='string'?payload.detail:'本地工作区请求失败'}catch{return '本地工作区请求失败'}
}

async function localRequest<T>(path:string,options:LocalRequestOptions={}):Promise<T>{
  const controller=new AbortController();const timeout=window.setTimeout(()=>controller.abort(),options.timeoutMs??10_000)
  try{
    const request=new Request(`${LOCAL_WORKSPACE_ORIGIN}${path}`,{
      ...options,
      signal:controller.signal,
      headers:{'Content-Type':'application/json',...(options.headers||{})},
      cache:'no-store',
      credentials:'omit',
      mode:'cors',
      // Chrome/Edge 142+ requires an explicit loopback request so it can
      // present the one-time "local network access" permission prompt.
      targetAddressSpace:'loopback',
    } as LoopbackRequestInit)
    const response=await fetch(request)
    if(!response.ok)throw new Error(await localError(response))
    return await response.json() as T
  }catch(error){
    if((error as Error).name==='AbortError')throw new LocalAssistantAccessError('timeout','本地助手响应超时，请确认桌面快捷方式已启动')
    if(error instanceof TypeError)throw new LocalAssistantAccessError('browser_access_blocked','浏览器未能访问本地助手。请允许本站的“本地网络访问”权限后重试')
    throw error
  }finally{window.clearTimeout(timeout)}
}

export type LocalHealth={status:string;ffmpeg_ready:boolean;workspace_root:string;version?:string;capabilities?:string[];picker_ready?:boolean;picker_reason?:string;windows_user?:string;session_id?:number;session_state?:number;interactive_user?:string;shell_session_id?:number;active_console_session_id?:number}

export const NATIVE_FOLDER_PICKER_CAPABILITY='native_folder_picker_v2'

let cachedHealth:{value:LocalHealth;expiresAt:number}|undefined
let healthRequest:Promise<LocalHealth>|undefined

async function assistantHealth(force=false,timeoutMs=1800):Promise<LocalHealth>{
  if(!force&&cachedHealth&&cachedHealth.expiresAt>Date.now())return cachedHealth.value
  if(!force&&healthRequest)return healthRequest
  const request=localRequest<LocalHealth>('/api/local/health',{timeoutMs}).then(value=>{
    cachedHealth={value,expiresAt:Date.now()+30_000}
    return value
  }).finally(()=>{healthRequest=undefined})
  if(!force)healthRequest=request
  return request
}

export function localAssistantUnavailable(error:unknown){
  return error instanceof LocalAssistantAccessError
}

export function localAssistantSupports(health:LocalHealth,capability:string){
  return health.capabilities?.includes(capability)===true
}

export const localWorkspace={
  health:()=>assistantHealth(),
  requestAccess:()=>assistantHealth(true,15_000),
  get:(dramaId:number)=>localRequest<LocalWorkspace>(`/api/local/workspaces/${dramaId}`,{timeoutMs:2500}),
  syncCover:(dramaId:number,kind:'vertical'|'square'|'horizontal',file:Blob)=>localRequest<LocalWorkspace>(`/api/local/workspaces/${dramaId}/covers/${kind}`,{
    method:'PUT',timeoutMs:60_000,headers:{'Content-Type':file.type||'application/octet-stream'},body:file,
  }),
  select:(drama:Drama)=>localRequest<LocalWorkspace>('/api/local/workspaces/select',{
    method:'POST',timeoutMs:310_000,body:JSON.stringify({
      drama_id:drama.id,title:drama.title,theater:drama.theater,description:drama.description,
      genres:drama.genres,language:drama.language,total_episode_count:drama.total_episode_count,
    }),
  }),
  factoryAnalysis:(dramaId:number)=>localRequest<FactoryAnalysis>(`/api/factory/${dramaId}/analysis`),
  importFactoryAnalysis:(dramaId:number,body:FactoryAnalysis)=>localRequest<FactoryAnalysis>(`/api/local/workspaces/${dramaId}/analysis`,{method:'PUT',body:JSON.stringify(body)}),
  analyzeFactory:(dramaId:number)=>localRequest<FactoryAnalysis>(`/api/factory/${dramaId}/analyze`,{method:'POST'}),
  reviewFactoryAnalysis:(dramaId:number,body:{episode:string;kind:'high_energy'|'sensitive';start:number;end:number;decision:'approved'|'rejected'|'pending';new_start?:number;new_end?:number})=>localRequest<FactoryAnalysis>(`/api/factory/${dramaId}/analysis/review`,{method:'PATCH',body:JSON.stringify(body)}),
  startFactoryProcessing:(dramaId:number,body:{max_duration_seconds:number;hook_duration_seconds:number;publish_variant_count:number;remove_sensitive:boolean;compression_profile:'balanced'|'small';output_modes:FactoryOutputMode[];hooks_per_variant:number;hook_ids:number[]})=>localRequest<FactoryJob>(`/api/factory/${dramaId}/process`,{method:'POST',body:JSON.stringify(body)}),
  factoryJobs:(dramaId:number)=>localRequest<FactoryJob[]>(`/api/factory/${dramaId}/jobs`),
  factoryAssets:(dramaId:number)=>localRequest<GeneratedAsset[]>(`/api/factory/${dramaId}/assets`),
  videoUrl:(dramaId:number,episode:string)=>`${LOCAL_WORKSPACE_ORIGIN}/api/factory/${dramaId}/analysis/video/${encodeURIComponent(episode)}`,
  frameUrl:(dramaId:number,filename:string)=>`${LOCAL_WORKSPACE_ORIGIN}/api/factory/${dramaId}/analysis/frames/${encodeURIComponent(filename)}`,
  assetUrl:(assetId:number)=>`${LOCAL_WORKSPACE_ORIGIN}/api/factory/assets/${assetId}/download`,
  metaFactorySource:(dramaId:number)=>localRequest<MetaFactorySource>(`/api/meta-sfs/source/${dramaId}`),
  selectMetaOutputDirectory:()=>localRequest<{token:string;name:string}>('/api/meta-sfs/select-local-directory',{method:'POST',timeoutMs:310_000}),
  metaPreflight:(body:MetaSFSInput)=>localRequest<MetaPreflight>('/api/meta-sfs/preflight?quick=true',{method:'POST',timeoutMs:30_000,body:JSON.stringify(body)}),
  buildMetaPackage:(body:MetaSFSInput)=>localRequest<MetaPackage>('/api/meta-sfs/build',{method:'POST',timeoutMs:120_000,body:JSON.stringify(body)}),
  metaPackages:()=>localRequest<MetaPackage[]>('/api/meta-sfs/packages'),
  metaPackage:(id:number)=>localRequest<MetaPackage>(`/api/meta-sfs/packages/${id}`),
  metaPackageFiles:(id:number)=>localRequest<MetaPackageFiles>(`/api/meta-sfs/packages/${id}/files`),
  metaPackageFileUrl:(id:number,path:string)=>`${LOCAL_WORKSPACE_ORIGIN}/api/meta-sfs/packages/${id}/files/${path.split('/').map(encodeURIComponent).join('/')}`,
  metaPackageArchiveUrl:(id:number)=>`${LOCAL_WORKSPACE_ORIGIN}/api/meta-sfs/packages/${id}/archive`,
  openMetaPackageFolder:(id:number)=>localRequest<{opened:boolean;path:string}>(`/api/meta-sfs/packages/${id}/open-folder`,{method:'POST'}),
  copyMetaPackageLocal:(id:number,token:string)=>localRequest<{path:string;folder_name:string}>(`/api/meta-sfs/packages/${id}/copy-local?token=${encodeURIComponent(token)}`,{method:'POST'}),
  modelUsage:()=>localRequest<LocalModelUsage[]>('/api/local/usage/model-events'),
}
