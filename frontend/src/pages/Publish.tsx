import {
 CalendarOutlined,CheckCircleOutlined,ClockCircleOutlined,CopyOutlined,EditOutlined,FolderOpenOutlined,InboxOutlined,LinkOutlined,
 PictureOutlined,ReloadOutlined,RocketOutlined,SafetyCertificateOutlined,SmileOutlined,SyncOutlined,TagOutlined,ThunderboltOutlined,
} from '@ant-design/icons'
import {
 Alert,Button,Card,Checkbox,DatePicker,Descriptions,Empty,Form,Image,Input,Modal,Popover,Progress,Radio,Segmented,Select,
 Space,Switch,Table,Tag,Typography,Upload,message,type UploadFile,
} from 'antd'
import dayjs from 'dayjs'
import { useEffect,useMemo,useRef,useState } from 'react'
import { useNavigate,useSearchParams } from 'react-router-dom'
import type { TextAreaRef } from 'antd/es/input/TextArea'
import { api,type Account,type AccountStrategy,type Clip,type Drama,type IntegrationConfig,type Post,type PublishJob,type TitleCandidate } from '../api'
import { PlatformBadge,PlatformOption } from '../components/PlatformBrand'
import { useAuth } from '../auth'
import { getLocalBindings,getLocalStrategies } from '../localStrategies'

type CoverKind='vertical'|'square'|'horizontal'
type ContentDraft={clipId:number;title:string;caption:string;hashtags:string[];firstComment:string;formula:number;hitWords:string[]}

const statusMeta:Record<string,{label:string;color:string}>={
 queued:{label:'等待排期',color:'blue'},uploading:{label:'正在上传',color:'processing'},submitted:{label:'平台处理中',color:'gold'},
 published:{label:'已发布',color:'success'},failed:{label:'失败',color:'error'},blocked:{label:'已阻止',color:'warning'},
}
const filename=(path:string)=>path.split(/[\\/]/).pop()||path
const theaterTag=(theater='')=>`#${theater.trim().replace(/^#+/,'').replace(/\s+/g,'')}`
const preferredCover=(drama?:Drama):CoverKind|undefined=>drama?.cover_horizontal_path?'horizontal':undefined
const blankDraft=(clipId:number):ContentDraft=>({clipId,title:'',caption:'',hashtags:[],firstComment:'',formula:1,hitWords:[]})
const normalizeTag=(value:string)=>{const clean=value.trim().replace(/^#+/,'').replace(/[^\p{L}\p{N}_]+/gu,'');return clean?`#${clean}`:''}
const extractTags=(value:string)=>Array.from(new Set(Array.from(value.matchAll(/#[\p{L}\p{N}_]+/gu),match=>normalizeTag(match[0])).filter(Boolean)))
const captionWithTags=(caption:string,tags:string[])=>{
 const missing=tags.map(normalizeTag).filter(Boolean).filter(tag=>!caption.toLocaleLowerCase().includes(tag.toLocaleLowerCase()))
 return missing.length?`${caption.trim()}\n${missing.join(' ')}`:caption.trim()
}

export default function Publish({embedded=false}:{embedded?:boolean}){
 const[params]=useSearchParams();const navigate=useNavigate();const{user}=useAuth()
 const[dramas,setDramas]=useState<Drama[]>([]);const[clips,setClips]=useState<Clip[]>([]);const[accounts,setAccounts]=useState<Account[]>([])
 const[strategies,setStrategies]=useState<AccountStrategy[]>([]);const[posts,setPosts]=useState<Post[]>([]);const[jobs,setJobs]=useState<PublishJob[]>([])
 const[bindings,setBindings]=useState<Record<string,number>>({})
 const[integration,setIntegration]=useState<IntegrationConfig>();const[view,setView]=useState<'workflow'|'records'>('workflow')
 const[dramaId,setDramaId]=useState<number>();const[selectedClips,setSelectedClips]=useState<number[]>([]);const[clipAccounts,setClipAccounts]=useState<Record<number,number[]>>({});const[bulkAccounts,setBulkAccounts]=useState<number[]>([])
 const[strategyId,setStrategyId]=useState<number>();const[language,setLanguage]=useState('English')
 const[includeTheaterTag,setIncludeTheaterTag]=useState(true)
 const[drafts,setDrafts]=useState<ContentDraft[]>([]);const[provider,setProvider]=useState('');const[coverKind,setCoverKind]=useState<CoverKind>()
 const[contentSourceClipId,setContentSourceClipId]=useState<number>()
 const[aiAssistOpen,setAiAssistOpen]=useState(false);const captionRefs=useRef<Record<number,TextAreaRef|null>>({})
 const[mode,setMode]=useState<'now'|'schedule'>('now');const[generating,setGenerating]=useState(false);const[working,setWorking]=useState(false)
 const[uploadOpen,setUploadOpen]=useState(false);const[uploadFiles,setUploadFiles]=useState<UploadFile[]>([]);const[uploadProgress,setUploadProgress]=useState<Record<string,number>>({})
 const[uploading,setUploading]=useState(false);const[checking,setChecking]=useState<number|null>(null)
 const[tiktokPrivacy,setTikTokPrivacy]=useState<string[]>([]);const[form]=Form.useForm();const[msg,ctx]=message.useMessage()

 const load=async(force=false)=>{
  const[d,c,a,p,j,i]=await Promise.all([api.list(force),api.clips(undefined,force),api.accounts(force),api.posts(force),api.publishJobs(force),api.integrationConfig(force)])
  setDramas(d);setClips(c);setAccounts(a);setStrategies(getLocalStrategies(user.id));setBindings(getLocalBindings(user.id));setPosts(p);setJobs(j);setIntegration(i)
  if(!dramaId){const requested=Number(params.get('drama'));const picked=d.find(x=>x.id===requested)||d[0];if(picked){const latest=c.find(x=>x.drama_id===picked.id&&x.status==='approved');setDramaId(picked.id);setCoverKind(preferredCover(picked));form.setFieldValue('ai_disclosure',picked.is_ai_generated);if(latest){setSelectedClips([latest.id]);setDrafts([blankDraft(latest.id)]);setContentSourceClipId(latest.id)}}}
 }
 useEffect(()=>{load().catch(e=>msg.error(e.message))},[])

 const drama=dramas.find(x=>x.id===dramaId)
 const readyClips=clips.filter(x=>x.drama_id===dramaId&&x.status==='approved')
 const connected=accounts.filter(x=>x.status==='connected')
 const selectedAccounts=Array.from(new Set(selectedClips.flatMap(id=>clipAccounts[id]||[])))
 const selectedAccountRows=accounts.filter(x=>selectedAccounts.includes(x.id))
 const platforms=new Set(selectedAccountRows.map(x=>x.platform))
 const requiresHorizontalCover=platforms.has('youtube')
 const selectedDrafts=selectedClips.map(id=>drafts.find(x=>x.clipId===id)||blankDraft(id))
 const mappedJobCount=selectedClips.reduce((total,id)=>total+(clipAccounts[id]?.length||0),0)
 const allClipsAssigned=selectedClips.length>0&&selectedClips.every(id=>(clipAccounts[id]?.length||0)>0)
 const selectedStrategy=strategies.find(x=>x.id===strategyId)
 const aiUnavailableReason=!selectedClips.length?'请先选择视频':!allClipsAssigned?'请为每个视频匹配账号':''
 const coverChoices=useMemo(()=>drama?.cover_horizontal_path?[{kind:'horizontal' as const,title:'横版封面',ratio:'16:9',path:drama.cover_horizontal_path}]:[],[drama])
 const overallUploadPercent=useMemo(()=>uploadFiles.length?Math.round(uploadFiles.reduce((sum,file)=>sum+(uploadProgress[file.uid]||0),0)/uploadFiles.length):0,[uploadFiles,uploadProgress])

 const changeDrama=(id:number)=>{const next=dramas.find(x=>x.id===id);const latest=clips.find(x=>x.drama_id===id&&x.status==='approved');setDramaId(id);setSelectedClips(latest?[latest.id]:[]);setDrafts(latest?[blankDraft(latest.id)]:[]);setContentSourceClipId(latest?.id);setClipAccounts({});setBulkAccounts([]);setProvider('');setIncludeTheaterTag(true);setAiAssistOpen(false);setCoverKind(preferredCover(next));form.setFieldValue('ai_disclosure',Boolean(next?.is_ai_generated))}
 const changeClips=(ids:number[])=>{
  setSelectedClips(ids)
  setDrafts(rows=>ids.map(id=>rows.find(x=>x.clipId===id)||blankDraft(id)))
  setContentSourceClipId(current=>current&&ids.includes(current)?current:ids[0])
  setClipAccounts(rows=>Object.fromEntries(ids.filter(id=>rows[id]?.length).map(id=>[id,rows[id]])))
 }
 const syncAccountSettings=async(ids:number[])=>{
  const first=accounts.find(x=>x.id===ids[0]);setStrategyId(first?bindings[String(first.id)]:undefined)
  const includesYouTube=accounts.some(x=>ids.includes(x.id)&&x.platform==='youtube');setCoverKind(includesYouTube?preferredCover(drama):undefined)
  const tiktok=accounts.filter(x=>ids.includes(x.id)&&x.platform==='tiktok');if(!tiktok.length){setTikTokPrivacy([]);return}
  try{const info=await Promise.all(tiktok.map(x=>api.creatorInfo(x.id)));const available=info.map(x=>x.privacy_level_options).reduce((a,b)=>a.filter(x=>b.includes(x)));setTikTokPrivacy(available);if(available.length===1)form.setFieldValue('tiktok_privacy',available[0])}catch(e){setTikTokPrivacy([]);msg.error((e as Error).message)}
 }
 const changeClipAccounts=(clipId:number,ids:number[])=>{
  const next={...clipAccounts,[clipId]:ids};setClipAccounts(next)
  void syncAccountSettings(Array.from(new Set(selectedClips.flatMap(id=>next[id]||[]))))
 }
 const applyBulkAccounts=()=>{
  if(!selectedClips.length){msg.info('请先选择视频');return}
  if(!bulkAccounts.length){msg.info('请选择要批量应用的账号');return}
  const next=Object.fromEntries(selectedClips.map(id=>[id,bulkAccounts]));setClipAccounts(next);void syncAccountSettings(bulkAccounts);msg.success(`已为 ${selectedClips.length} 个视频匹配账号`)
 }
 const uploadLocalFiles=async()=>{
  if(!drama||!uploadFiles.length){msg.error(drama?'请选择本地视频':'请先选择剧目');return}
  const before=new Set(clips.map(x=>x.id));setUploading(true);setUploadProgress({})
  try{
   for(const row of uploadFiles){const file=row.originFileObj as File|undefined;if(!file)continue;await api.uploadVideo(drama.title,'一键发布本地上传',file,percent=>setUploadProgress(old=>({...old,[row.uid]:percent})),'publish')}
   const rows=await api.clips(drama.id);setClips(old=>[...old.filter(x=>x.drama_id!==drama.id),...rows]);const created=rows.filter(x=>!before.has(x.id)&&x.status==='approved').map(x=>x.id)
   setSelectedClips(previous=>{const next=Array.from(new Set([...previous,...created]));setDrafts(existing=>next.map(id=>existing.find(x=>x.clipId===id)||blankDraft(id)));return next})
   setUploadFiles([]);setUploadOpen(false);msg.success(`${created.length} 个视频已加入发布清单`)
  }catch(e){msg.error((e as Error).message)}finally{setUploading(false);setUploadProgress({})}
 }
 const generate=async()=>{
  if(!allClipsAssigned){msg.error('请先为每个视频匹配发布账号');return}
  setGenerating(true)
  try{
   const results=await Promise.all(selectedClips.map(id=>{const account=accounts.find(x=>x.id===(clipAccounts[id]||[])[0])!;return api.generateTitles(id,account.account_type,language,'auto',account.id,[],selectedStrategy,includeTheaterTag)}))
   setDrafts(rows=>selectedClips.map((clipId,index)=>{const previous=rows.find(row=>row.clipId===clipId)||blankDraft(clipId);const candidate=results[index].candidates.find(x=>!x.hit_words.length)||results[index].candidates[0];return{...previous,title:candidate.title,caption:captionWithTags(candidate.caption,candidate.hashtags),hashtags:candidate.hashtags.map(normalizeTag).filter(Boolean),formula:candidate.formula,hitWords:candidate.hit_words}}))
   setProvider(Array.from(new Set(results.map(x=>x.provider))).join(' / '));msg.success(`已生成 ${results.length} 组可编辑内容`)
  }catch(e){msg.error((e as Error).message)}finally{setGenerating(false)}
 }
 const editDraft=(clipId:number,patch:Partial<ContentDraft>)=>setDrafts(rows=>selectedClips.map(id=>{const row=rows.find(item=>item.clipId===id)||blankDraft(id);return id===clipId?{...row,...patch}:row}))
 const applyContentToAll=()=>{
  if(selectedClips.length<2){msg.info('请先选择至少两个视频');return}
  const sourceId=contentSourceClipId??selectedClips[0]
  const source=selectedDrafts.find(draft=>draft.clipId===sourceId)
  if(!source?.title.trim()&&!source?.caption.trim()&&!source?.firstComment.trim()){msg.info('请先填写作为模板的视频内容');return}
  setDrafts(selectedClips.map(clipId=>({
   ...source,
   clipId,
   hashtags:[...source.hashtags],
   hitWords:[...source.hitWords],
  })))
  msg.success(`已将发布内容应用到 ${selectedClips.length} 个视频`)
 }
 const insertIntoCaption=(draft:ContentDraft,text:string)=>{
  const textarea=captionRefs.current[draft.clipId]?.resizableTextArea?.textArea
  const start=textarea?.selectionStart??draft.caption.length;const end=textarea?.selectionEnd??start
  const before=draft.caption.slice(0,start);const after=draft.caption.slice(end)
  const next=`${before}${text}${after}`;const cursor=start+text.length
  editDraft(draft.clipId,{caption:next,hashtags:extractTags(next)})
  requestAnimationFrame(()=>{const node=captionRefs.current[draft.clipId]?.resizableTextArea?.textArea;node?.focus();node?.setSelectionRange(cursor,cursor)})
 }
 const focusForSystemEmoji=(draft:ContentDraft)=>{
  const textarea=captionRefs.current[draft.clipId]?.resizableTextArea?.textArea
  textarea?.focus()
  const cursor=textarea?.selectionStart??draft.caption.length
  textarea?.setSelectionRange(cursor,cursor)
 }

 const submit=async(values:any)=>{
  if(!drama||!selectedClips.length||!allClipsAssigned){msg.error('请为每个视频至少匹配一个发布账号');return}
  if(requiresHorizontalCover&&(!drama.cover_horizontal_path||coverKind!=='horizontal')){msg.error('发布到 YouTube 前，请先在剧库上传 16:9 横版封面');return}
  if(selectedDrafts.length!==selectedClips.length){msg.error('请先生成全部标题和文案');return}
  if(selectedDrafts.some(x=>!x.title.trim()||!x.caption.trim())){msg.error('标题和文案不能为空');return}
  const instagramDrafts=selectedDrafts.filter(draft=>(clipAccounts[draft.clipId]||[]).some(id=>accounts.find(account=>account.id===id)?.platform==='instagram'))
  const missingInstagram=!integration?.public_media_ready&&instagramDrafts.some(x=>!String(values[`instagram_url_${x.clipId}`]||'').startsWith('https://'))
  if(missingInstagram){msg.error('Instagram 需要每个视频的公网 HTTPS 地址');return}
  const time=mode==='now'?new Date().toISOString():values.scheduled_at.toISOString()
  Modal.confirm({width:620,title:'确认创建发布任务？',icon:<SafetyCertificateOutlined/>,okText:mode==='now'?'确认发布':'确认排期',content:<Descriptions bordered size="small" column={1} items={[
   {key:'content',label:'批量任务',children:`${selectedDrafts.length} 个视频，共 ${mappedJobCount} 个发布任务`},
   {key:'accounts',label:'视频与账号',children:<div className="publish-confirm-mapping">{selectedDrafts.map(draft=><div key={draft.clipId}><b>{filename(clips.find(x=>x.id===draft.clipId)?.file_path||'视频')}</b><Space wrap>{(clipAccounts[draft.clipId]||[]).map(id=>{const account=accounts.find(x=>x.id===id);return account?<PlatformOption key={id} platform={account.platform} label={account.name}/>:null})}</Space></div>)}</div>},
   {key:'cover',label:'发布封面',children:requiresHorizontalCover?(coverChoices.find(x=>x.kind===coverKind)?.title||'未选择'):'平台自动取视频帧'},
   {key:'time',label:'执行时间',children:new Date(time).toLocaleString()},
  ]}/>,onOk:async()=>{
   setWorking(true)
   try{
    const created:Post[]=[]
    for(const draft of selectedDrafts){const account=accounts.find(x=>x.id===(clipAccounts[draft.clipId]||[])[0]);const candidate:TitleCandidate={formula:draft.formula,title:draft.title.trim(),caption:captionWithTags(draft.caption,draft.hashtags),hashtags:draft.hashtags,hit_words:draft.hitWords};created.push(await api.createPost(draft.clipId,account?.account_type||'official',candidate))}
    const options:Record<string,unknown>={cover_kind:requiresHorizontalCover?coverKind:undefined,youtube_privacy:values.youtube_privacy||'private',made_for_kids:Boolean(values.made_for_kids),tiktok_privacy:values.tiktok_privacy,disable_duet:Boolean(values.disable_duet),disable_comment:Boolean(values.disable_comment),disable_stitch:Boolean(values.disable_stitch),facebook_published:values.facebook_published!==false,instagram_video_urls:Object.fromEntries(created.map((post,index)=>[String(post.id),values[`instagram_url_${selectedDrafts[index].clipId}`]||''])),first_comments:Object.fromEntries(created.map((post,index)=>[String(post.id),selectedDrafts[index].firstComment.trim()]))}
    const assignments=created.map((post,index)=>({post_id:post.id,account_ids:clipAccounts[selectedDrafts[index].clipId]||[]}))
    await api.mappedBatchPublish(assignments,time,mode==='now',Boolean(values.ai_disclosure),options)
    setPosts(old=>[...created.reverse(),...old]);await load();setView('records');msg.success(mode==='now'?'已提交平台，正在任务记录中跟踪':'发布排期已保存')
   }catch(e){msg.error((e as Error).message);throw e}finally{setWorking(false)}
  }})
 }
 const run=async(id:number)=>{setChecking(id);try{const result=await api.runPublishJob(id);result.status==='failed'||result.status==='blocked'?msg.error(result.result_log):msg.success('任务已提交平台');await load()}catch(e){msg.error((e as Error).message)}finally{setChecking(null)}}
 const refresh=async(id:number)=>{setChecking(id);try{await api.refreshPublishJob(id);await load()}catch(e){msg.error((e as Error).message)}finally{setChecking(null)}}

 return <div className="workspace-page unified-publish">{ctx}
  <div className="page-heading publish-page-heading"><Typography.Title level={2}>一键发布</Typography.Title><Space wrap><Select className="publish-drama-select" showSearch optionFilterProp="label" value={dramaId} onChange={changeDrama} placeholder="选择剧目" options={dramas.map(x=>({value:x.id,label:x.title}))}/><Button icon={<FolderOpenOutlined/>} disabled={!drama} onClick={()=>setUploadOpen(true)}>上传视频</Button></Space></div>
  <div className="workflow-view-switch"><Segmented value={view} onChange={v=>setView(v as typeof view)} options={[{label:'创建发布',value:'workflow',icon:<RocketOutlined/>},{label:'任务记录',value:'records',icon:<ClockCircleOutlined/>}]}/></div>
  {view==='workflow'?<>
   <Form form={form} layout="vertical" onFinish={submit} initialValues={{ai_disclosure:false,youtube_privacy:'private',facebook_published:true}}>
    <Card className="publish-flow-card publish-source-card" title="批量发布清单" extra={mappedJobCount?<Tag color="green">{mappedJobCount} 个发布任务</Tag>:undefined}>
     <Form.Item label="选择发布视频"><Select mode="multiple" value={selectedClips} onChange={changeClips} optionFilterProp="label" placeholder="选择内容工厂成品或本地上传" options={readyClips.map(x=>({value:x.id,label:`${filename(x.file_path)}${x.template_name==='local_upload'?' · 本地上传':''}`}))}/></Form.Item>
     {!!selectedClips.length&&<div className="publish-mapping-panel">
      <div className="publish-mapping-toolbar"><div><b>视频与账号匹配</b><span>每个视频可以选择一个或多个发布账号</span></div><Space.Compact className="publish-bulk-assign"><Select mode="multiple" value={bulkAccounts} onChange={setBulkAccounts} optionFilterProp="label" placeholder="批量选择账号" options={connected.map(x=>({value:x.id,label:<PlatformOption platform={x.platform} label={x.name}/>}))}/><Button onClick={applyBulkAccounts}>应用到全部</Button></Space.Compact></div>
      <div className="publish-mapping-list">{selectedClips.map((clipId,index)=><div className="publish-mapping-row" key={clipId}><span className="publish-mapping-index">{String(index+1).padStart(2,'0')}</span><div className="publish-mapping-video"><b>{filename(clips.find(x=>x.id===clipId)?.file_path||'视频')}</b><small>{clips.find(x=>x.id===clipId)?.template_name==='local_upload'?'本地上传':'内容工厂成品'}</small></div><Select mode="multiple" value={clipAccounts[clipId]||[]} onChange={ids=>changeClipAccounts(clipId,ids)} optionFilterProp="label" status={(clipAccounts[clipId]?.length||0)?undefined:'error'} placeholder="选择该视频的发布账号" options={connected.map(x=>({value:x.id,label:<PlatformOption platform={x.platform} label={x.name}/>}))}/></div>)}</div>
     </div>}
     <div className="publish-cover-title"><PictureOutlined/><b>发布封面</b>{requiresHorizontalCover&&<Tag color="red">YouTube · 16:9 横版</Tag>}<Button type="link" size="small" icon={<EditOutlined/>} onClick={()=>navigate(`/dramas/${drama?.id??''}`)}>管理封面</Button></div>
     {requiresHorizontalCover&&(coverChoices.length
      ?<Radio.Group className="publish-cover-picker is-required" value={coverKind} onChange={e=>setCoverKind(e.target.value)}>{coverChoices.map(item=><Radio.Button value={item.kind} key={item.kind}><Image preview={false} src={`/api/dramas/${drama?.id}/covers/${item.kind}`}/><span>{item.title}<small>{item.ratio}</small></span></Radio.Button>)}</Radio.Group>
      :<Alert type="error" showIcon message="YouTube 缺少 16:9 横版封面" action={<Button size="small" onClick={()=>navigate(`/dramas/${drama?.id??''}`)}>上传横版封面</Button>}/>)}
     {!!selectedAccounts.length&&<Space wrap className="publish-cover-platforms">{platforms.has('youtube')&&<Tag color="green"><PlatformBadge platform="youtube" size={14}/> 横版封面</Tag>}{platforms.has('tiktok')&&<Tag><PlatformBadge platform="tiktok" size={14}/> 视频第 1 秒</Tag>}{platforms.has('instagram')&&<Tag><PlatformBadge platform="instagram" size={14}/> 视频首帧</Tag>}{platforms.has('facebook')&&<Tag><PlatformBadge platform="facebook" size={14}/> 平台自动生成</Tag>}</Space>}
    </Card>

    <Card className="publish-flow-card publish-composer-card" title="发布内容">
     {!!selectedAccountRows.length&&<div className="publish-account-strip">{selectedAccountRows.map(x=><span key={x.id}><PlatformBadge platform={x.platform} size={20}/>{x.name}</span>)}</div>}
     {selectedDrafts.length>1&&<div className="publish-copy-toolbar"><div><CopyOutlined/><span><b>复用发布内容</b><small>复制标题、文案、标签和首条评论，不改变账号匹配</small></span></div><Space.Compact><Select value={contentSourceClipId??selectedClips[0]} onChange={setContentSourceClipId} optionFilterProp="label" options={selectedDrafts.map((draft,index)=>({value:draft.clipId,label:`${index+1}. ${filename(clips.find(x=>x.id===draft.clipId)?.file_path||'视频')}`}))}/><Button icon={<CopyOutlined/>} onClick={applyContentToAll}>应用到全部视频</Button></Space.Compact></div>}
     {selectedDrafts.length?<div className="publish-draft-list">{selectedDrafts.map((draft,index)=><Card size="small" key={draft.clipId} title={`${index+1}. ${filename(clips.find(x=>x.id===draft.clipId)?.file_path||'视频')}`} extra={draft.hitWords.map(x=><Tag color="red" key={x}>{x}</Tag>)}><div className="publish-draft-targets"><span>发布到</span><Space wrap>{(clipAccounts[draft.clipId]||[]).map(id=>{const account=accounts.find(x=>x.id===id);return account?<span key={id}><PlatformBadge platform={account.platform} size={15}/>{account.name}</span>:null})}{!(clipAccounts[draft.clipId]?.length)&&<Tag color="red">尚未匹配账号</Tag>}</Space></div><Form.Item label="标题" required><Input showCount maxLength={99} value={draft.title} onChange={e=>editDraft(draft.clipId,{title:e.target.value})} placeholder="手动输入发布标题"/></Form.Item><Form.Item label="文案" required><Input.TextArea ref={node=>{captionRefs.current[draft.clipId]=node}} className="publish-caption-editor" autoSize={{minRows:5,maxRows:14}} value={draft.caption} onChange={e=>editDraft(draft.clipId,{caption:e.target.value,hashtags:extractTags(e.target.value)})} placeholder="输入发布文案"/></Form.Item><div className="publish-editor-tools"><Button type="text" size="small" icon={<SmileOutlined/>} onClick={()=>focusForSystemEmoji(draft)} title="Windows：Win + .；macOS：Control + Command + 空格">表情 · Win + .</Button><Button type="text" size="small" icon={<TagOutlined/>} onClick={()=>insertIntoCaption(draft,'#')}>添加标签</Button><Button type={aiAssistOpen?'default':'text'} size="small" icon={<ThunderboltOutlined/>} onClick={()=>setAiAssistOpen(open=>!open)}>AI 辅助</Button></div><Form.Item label="首条评论"><Input.TextArea autoSize={{minRows:2,maxRows:5}} value={draft.firstComment} onChange={e=>editDraft(draft.clipId,{firstComment:e.target.value})} placeholder="可选，发布后作为真实首条评论发送"/></Form.Item></Card>)}</div>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={readyClips.length?'请选择发布视频':'暂无可发布视频'}/>}
     {aiAssistOpen&&<div className="publish-ai-assist">
      <div className="publish-ai-assist-heading"><ThunderboltOutlined/><div><b>AI 辅助撰写</b><span>按剧情、账号策略和参考样本生成，生成后仍可继续编辑</span></div></div>
      <div className="publish-ai-assist-settings"><Select allowClear value={strategyId} onChange={setStrategyId} placeholder="选择运营策略（可选）" options={strategies.filter(x=>x.confirmed).map(x=>({value:x.id,label:x.name}))}/><Input value={language} onChange={e=>setLanguage(e.target.value)} placeholder="目标语言"/>{drama?.theater&&<label><Switch size="small" checked={includeTheaterTag} onChange={setIncludeTheaterTag}/><span>{theaterTag(drama.theater)}</span></label>}</div>
      <div className="publish-ai-actions">{selectedStrategy&&<Popover placement="top" title={selectedStrategy.name} content={<div className="publish-reference-preview">{selectedStrategy.history_text}</div>}><Button size="small" type="link">查看参考样本</Button></Popover>}{provider&&<Tag color="green">{provider}</Tag>}<Button size="small" icon={<ThunderboltOutlined/>} loading={generating} disabled={Boolean(aiUnavailableReason)} onClick={generate}>AI 生成文案</Button></div>
     </div>}
    </Card>

    <Card className="publish-flow-card publish-settings-card" title="发布设置">
     <div className="publish-final-grid"><Form.Item label="发布时间"><Radio.Group value={mode} onChange={e=>setMode(e.target.value)} optionType="button" buttonStyle="solid" options={[{value:'now',label:'立即发布'},{value:'schedule',label:'定时发布'}]}/></Form.Item>{mode==='schedule'&&<Form.Item name="scheduled_at" label="计划时间" rules={[{required:true,message:'请选择时间'}]}><DatePicker showTime showNow disabledDate={date=>date.isBefore(dayjs().startOf('day'))}/></Form.Item>}<Form.Item name="ai_disclosure" label="AI 标注" valuePropName="checked"><Switch size="small" disabled={Boolean(drama?.is_ai_generated)}/></Form.Item></div>
     {platforms.size>0&&<div className="platform-settings">
      {platforms.has('youtube')&&<div className="platform-setting-row"><PlatformBadge platform="youtube" size={22}/><Form.Item name="youtube_privacy" label="可见性"><Select options={['private','unlisted','public'].map(x=>({value:x,label:x}))}/></Form.Item><Form.Item name="made_for_kids" label="儿童内容" valuePropName="checked"><Switch/></Form.Item></div>}
      {platforms.has('tiktok')&&<div className="platform-setting-block"><div className="platform-setting-row"><PlatformBadge platform="tiktok" size={22}/><Form.Item name="tiktok_privacy" label="可见性" rules={[{required:true}]}><Select options={tiktokPrivacy.map(x=>({value:x,label:x}))}/></Form.Item></div><Space wrap><Form.Item name="disable_comment" valuePropName="checked"><Checkbox>关闭评论</Checkbox></Form.Item><Form.Item name="disable_duet" valuePropName="checked"><Checkbox>关闭 Duet</Checkbox></Form.Item><Form.Item name="disable_stitch" valuePropName="checked"><Checkbox>关闭 Stitch</Checkbox></Form.Item></Space></div>}
      {platforms.has('facebook')&&<div className="platform-setting-row"><PlatformBadge platform="facebook" size={22}/><Form.Item name="facebook_published" label="立即公开" valuePropName="checked"><Switch/></Form.Item></div>}
      {platforms.has('instagram')&&<div className="platform-setting-block"><Space><PlatformBadge platform="instagram" size={22}/><b>Instagram 视频地址</b></Space>{selectedDrafts.filter(draft=>(clipAccounts[draft.clipId]||[]).some(id=>accounts.find(account=>account.id===id)?.platform==='instagram')).map(draft=><Form.Item key={draft.clipId} name={`instagram_url_${draft.clipId}`} label={filename(clips.find(x=>x.id===draft.clipId)?.file_path||'视频')} rules={[{required:!integration?.public_media_ready},{type:'url',message:'请输入 HTTPS 地址'}]}><Input prefix={<LinkOutlined/>} placeholder={integration?.public_media_ready?'可留空，由系统生成':'https://cdn.example.com/video.mp4'}/></Form.Item>)}</div>}
     </div>}
     <Button size="large" block type="primary" htmlType="submit" loading={working} disabled={!allClipsAssigned||!connected.length} icon={mode==='now'?<RocketOutlined/>:<CalendarOutlined/>}>{mode==='now'?`确认并发布 ${mappedJobCount} 个任务`:`确认 ${mappedJobCount} 个定时任务`}</Button>
    </Card>
   </Form>
  </>:<Card className="table-card" title="任务记录" extra={<Button icon={<ReloadOutlined/>} onClick={()=>load(true)}>刷新</Button>} styles={{body:{padding:0}}}><Table rowKey="id" dataSource={jobs} scroll={{x:1180}} locale={{emptyText:<Empty description="暂无发布任务"/>}} columns={[
   {title:'任务',dataIndex:'id',width:75,render:(x:number)=>`#${x}`},{title:'账号',dataIndex:'account_id',width:180,render:(x:number)=>{const account=accounts.find(a=>a.id===x);return account?<Space size={7}><PlatformBadge platform={account.platform}/><span>{account.name}</span></Space>:`#${x}`}},
   {title:'内容',dataIndex:'post_id',width:250,ellipsis:true,render:(x:number)=>posts.find(p=>p.id===x)?.title||`#${x}`},{title:'计划时间',dataIndex:'scheduled_at',width:175,render:(x:string)=>new Date(x).toLocaleString()},
   {title:'状态',dataIndex:'status',width:125,render:(x:string)=>{const meta=statusMeta[x]||{label:x,color:'default'};return <Tag color={meta.color} icon={['uploading','submitted'].includes(x)?<SyncOutlined spin/>:undefined}>{meta.label}</Tag>}},{title:'平台链接',width:210,render:(_:unknown,row:PublishJob)=>row.platform_url?<a href={row.platform_url} target="_blank">打开平台</a>:'—'},
   {title:'结果',dataIndex:'result_log',ellipsis:true},{title:'操作',fixed:'right' as const,width:175,render:(_:unknown,row:PublishJob)=><Space><Button size="small" loading={checking===row.id} disabled={!['queued','failed','blocked'].includes(row.status)} onClick={()=>run(row.id)} icon={<CheckCircleOutlined/>}>{row.status==='queued'?'执行':'重试'}</Button><Button size="small" loading={checking===row.id} disabled={row.status!=='submitted'} onClick={()=>refresh(row.id)} icon={<SyncOutlined/>}>查状态</Button></Space>},
  ]}/></Card>}
  <Modal title="本地上传发布视频" open={uploadOpen} onCancel={()=>{if(!uploading){setUploadOpen(false);setUploadFiles([]);setUploadProgress({})}}} okText="上传并加入清单" cancelText="取消" confirmLoading={uploading} okButtonProps={{disabled:!uploadFiles.length}} onOk={uploadLocalFiles} maskClosable={!uploading} closable={!uploading}>
   <Upload.Dragger accept="video/*,.mp4,.mov,.mkv,.webm" multiple beforeUpload={()=>false} fileList={uploadFiles} onChange={({fileList})=>setUploadFiles(fileList)} disabled={uploading}><p className="ant-upload-drag-icon"><InboxOutlined/></p><p className="ant-upload-text">选择一个或多个本地视频</p></Upload.Dragger>
   {!!uploadFiles.length&&<div className="factory-upload-summary"><div><b>{uploadFiles.length} 个视频</b><span>{uploading?`上传中 ${overallUploadPercent}%`:'等待上传'}</span></div>{uploading&&<Progress percent={overallUploadPercent} showInfo={false}/>}</div>}
  </Modal>
 </div>
}
