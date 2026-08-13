import {
 CalendarOutlined,CheckCircleOutlined,ClockCircleOutlined,EditOutlined,FolderOpenOutlined,InboxOutlined,LinkOutlined,
 PictureOutlined,ReloadOutlined,RocketOutlined,SafetyCertificateOutlined,SyncOutlined,ThunderboltOutlined,
} from '@ant-design/icons'
import {
 Alert,Button,Card,Checkbox,DatePicker,Descriptions,Empty,Form,Image,Input,Modal,Popover,Progress,Radio,Segmented,Select,
 Space,Steps,Switch,Table,Tag,Typography,Upload,message,type UploadFile,
} from 'antd'
import dayjs from 'dayjs'
import { useEffect,useMemo,useState } from 'react'
import { useNavigate,useSearchParams } from 'react-router-dom'
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
const preferredCover=(drama?:Drama):CoverKind|undefined=>drama?.cover_horizontal_path?'horizontal':drama?.cover_vertical_path?'vertical':drama?.cover_square_path?'square':undefined
const blankDraft=(clipId:number):ContentDraft=>({clipId,title:'',caption:'',hashtags:[],firstComment:'',formula:1,hitWords:[]})

export default function Publish({embedded=false}:{embedded?:boolean}){
 const[params]=useSearchParams();const navigate=useNavigate();const{user}=useAuth()
 const[dramas,setDramas]=useState<Drama[]>([]);const[clips,setClips]=useState<Clip[]>([]);const[accounts,setAccounts]=useState<Account[]>([])
 const[strategies,setStrategies]=useState<AccountStrategy[]>([]);const[posts,setPosts]=useState<Post[]>([]);const[jobs,setJobs]=useState<PublishJob[]>([])
 const[bindings,setBindings]=useState<Record<string,number>>({})
 const[integration,setIntegration]=useState<IntegrationConfig>();const[view,setView]=useState<'workflow'|'records'>('workflow')
 const[dramaId,setDramaId]=useState<number>();const[selectedClips,setSelectedClips]=useState<number[]>([]);const[selectedAccounts,setSelectedAccounts]=useState<number[]>([])
 const[strategyId,setStrategyId]=useState<number>();const[language,setLanguage]=useState('English')
 const[includeTheaterTag,setIncludeTheaterTag]=useState(true)
 const[drafts,setDrafts]=useState<ContentDraft[]>([]);const[provider,setProvider]=useState('');const[coverKind,setCoverKind]=useState<CoverKind>()
 const[mode,setMode]=useState<'now'|'schedule'>('now');const[generating,setGenerating]=useState(false);const[working,setWorking]=useState(false)
 const[uploadOpen,setUploadOpen]=useState(false);const[uploadFiles,setUploadFiles]=useState<UploadFile[]>([]);const[uploadProgress,setUploadProgress]=useState<Record<string,number>>({})
 const[uploading,setUploading]=useState(false);const[checking,setChecking]=useState<number|null>(null)
 const[tiktokPrivacy,setTikTokPrivacy]=useState<string[]>([]);const[form]=Form.useForm();const[msg,ctx]=message.useMessage()

 const load=async(force=false)=>{
  const[d,c,a,p,j,i]=await Promise.all([api.list(force),api.clips(undefined,force),api.accounts(force),api.posts(force),api.publishJobs(force),api.integrationConfig(force)])
  setDramas(d);setClips(c);setAccounts(a);setStrategies(getLocalStrategies(user.id));setBindings(getLocalBindings(user.id));setPosts(p);setJobs(j);setIntegration(i)
  if(!dramaId){const requested=Number(params.get('drama'));const picked=d.find(x=>x.id===requested)||d[0];if(picked){const latest=c.find(x=>x.drama_id===picked.id&&x.status==='approved');setDramaId(picked.id);setCoverKind(preferredCover(picked));form.setFieldValue('ai_disclosure',picked.is_ai_generated);if(latest){setSelectedClips([latest.id]);setDrafts([blankDraft(latest.id)])}}}
 }
 useEffect(()=>{load().catch(e=>msg.error(e.message))},[])

 const drama=dramas.find(x=>x.id===dramaId)
 const readyClips=clips.filter(x=>x.drama_id===dramaId&&x.status==='approved')
 const connected=accounts.filter(x=>x.status==='connected')
 const selectedAccountRows=accounts.filter(x=>selectedAccounts.includes(x.id))
 const platforms=new Set(selectedAccountRows.map(x=>x.platform))
 const selectedDrafts=selectedClips.map(id=>drafts.find(x=>x.clipId===id)||blankDraft(id))
 const selectedStrategy=strategies.find(x=>x.id===strategyId)
 const aiUnavailableReason=!selectedClips.length?'请先选择视频':!selectedAccounts.length?'请先选择发布账号':''
 const contentReady=selectedDrafts.length===selectedClips.length&&selectedDrafts.every(x=>x.title.trim()&&x.caption.trim())
 const currentStep=!selectedClips.length?0:!selectedAccounts.length?1:!contentReady?2:3
 const coverChoices=useMemo(()=>drama?[
  {kind:'vertical' as const,title:'竖版',ratio:'3:4',path:drama.cover_vertical_path},
  {kind:'square' as const,title:'方形',ratio:'1:1',path:drama.cover_square_path},
  {kind:'horizontal' as const,title:'横版',ratio:'16:9',path:drama.cover_horizontal_path},
 ].filter(x=>Boolean(x.path)):[],[drama])
 const overallUploadPercent=useMemo(()=>uploadFiles.length?Math.round(uploadFiles.reduce((sum,file)=>sum+(uploadProgress[file.uid]||0),0)/uploadFiles.length):0,[uploadFiles,uploadProgress])

 const changeDrama=(id:number)=>{const next=dramas.find(x=>x.id===id);const latest=clips.find(x=>x.drama_id===id&&x.status==='approved');setDramaId(id);setSelectedClips(latest?[latest.id]:[]);setDrafts(latest?[blankDraft(latest.id)]:[]);setProvider('');setIncludeTheaterTag(true);setCoverKind(preferredCover(next));form.setFieldValue('ai_disclosure',Boolean(next?.is_ai_generated))}
 const changeClips=(ids:number[])=>{
  setSelectedClips(ids)
  setDrafts(rows=>ids.map(id=>rows.find(x=>x.clipId===id)||blankDraft(id)))
 }
 const changeAccounts=async(ids:number[])=>{
  setSelectedAccounts(ids);const first=accounts.find(x=>x.id===ids[0]);setStrategyId(first?bindings[String(first.id)]:undefined)
  const tiktok=accounts.filter(x=>ids.includes(x.id)&&x.platform==='tiktok');if(!tiktok.length){setTikTokPrivacy([]);return}
  try{const info=await Promise.all(tiktok.map(x=>api.creatorInfo(x.id)));const available=info.map(x=>x.privacy_level_options).reduce((a,b)=>a.filter(x=>b.includes(x)));setTikTokPrivacy(available);if(available.length===1)form.setFieldValue('tiktok_privacy',available[0])}catch(e){setTikTokPrivacy([]);msg.error((e as Error).message)}
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
  const account=selectedAccountRows[0];if(!account||!selectedClips.length){msg.error('请先选择视频和发布账号');return}
  setGenerating(true)
  try{
   const results=await Promise.all(selectedClips.map(id=>api.generateTitles(id,account.account_type,language,'auto',account.id,[],selectedStrategy,includeTheaterTag)))
   setDrafts(rows=>selectedClips.map((clipId,index)=>{const previous=rows.find(row=>row.clipId===clipId)||blankDraft(clipId);const candidate=results[index].candidates.find(x=>!x.hit_words.length)||results[index].candidates[0];return{...previous,title:candidate.title,caption:candidate.caption,hashtags:candidate.hashtags,formula:candidate.formula,hitWords:candidate.hit_words}}))
   setProvider(Array.from(new Set(results.map(x=>x.provider))).join(' / '));msg.success(`已生成 ${results.length} 组可编辑内容`)
  }catch(e){msg.error((e as Error).message)}finally{setGenerating(false)}
 }
 const editDraft=(clipId:number,patch:Partial<ContentDraft>)=>setDrafts(rows=>selectedClips.map(id=>{const row=rows.find(item=>item.clipId===id)||blankDraft(id);return id===clipId?{...row,...patch}:row}))

 const submit=async(values:any)=>{
  if(!drama||!selectedClips.length||!selectedAccounts.length){msg.error('请先完成视频与账号选择');return}
  if(!coverKind){msg.error('请先在剧库上传并选择封面');return}
  if(selectedDrafts.length!==selectedClips.length){msg.error('请先生成全部标题和文案');return}
  if(selectedDrafts.some(x=>!x.title.trim()||!x.caption.trim())){msg.error('标题和文案不能为空');return}
  const missingInstagram=platforms.has('instagram')&&!integration?.public_media_ready&&selectedDrafts.some(x=>!String(values[`instagram_url_${x.clipId}`]||'').startsWith('https://'))
  if(missingInstagram){msg.error('Instagram 需要每个视频的公网 HTTPS 地址');return}
  const time=mode==='now'?new Date().toISOString():values.scheduled_at.toISOString()
  Modal.confirm({width:620,title:'确认创建发布任务？',icon:<SafetyCertificateOutlined/>,okText:mode==='now'?'确认发布':'确认排期',content:<Descriptions bordered size="small" column={1} items={[
   {key:'content',label:'发布内容',children:`${selectedDrafts.length} 个视频 × ${selectedAccounts.length} 个账号`},
   {key:'accounts',label:'目标账号',children:<Space wrap>{selectedAccountRows.map(x=><PlatformOption key={x.id} platform={x.platform} label={x.name}/>)}</Space>},
   {key:'cover',label:'剧库封面',children:coverChoices.find(x=>x.kind===coverKind)?.title},
   {key:'time',label:'执行时间',children:new Date(time).toLocaleString()},
  ]}/>,onOk:async()=>{
   setWorking(true)
   try{
    const accountType=selectedAccountRows[0]?.account_type||'official'
    const created:Post[]=[]
    for(const draft of selectedDrafts){const candidate:TitleCandidate={formula:draft.formula,title:draft.title.trim(),caption:draft.caption.trim(),hashtags:draft.hashtags,hit_words:draft.hitWords};created.push(await api.createPost(draft.clipId,accountType,candidate))}
    const options:Record<string,unknown>={cover_kind:coverKind,youtube_privacy:values.youtube_privacy||'private',made_for_kids:Boolean(values.made_for_kids),tiktok_privacy:values.tiktok_privacy,disable_duet:Boolean(values.disable_duet),disable_comment:Boolean(values.disable_comment),disable_stitch:Boolean(values.disable_stitch),facebook_published:values.facebook_published!==false,instagram_video_urls:Object.fromEntries(created.map((post,index)=>[String(post.id),values[`instagram_url_${selectedDrafts[index].clipId}`]||''])),first_comments:Object.fromEntries(created.map((post,index)=>[String(post.id),selectedDrafts[index].firstComment.trim()]))}
    await api.batchPublish(created.map(x=>x.id),selectedAccounts,time,mode==='now',Boolean(values.ai_disclosure),options)
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
   <Card className="publish-steps"><Steps current={currentStep} responsive={false} items={[{title:'选择视频'},{title:'账号与 AI 参考'},{title:'编辑内容'},{title:'确认发布'}]}/></Card>
   <Form form={form} layout="vertical" onFinish={submit} initialValues={{ai_disclosure:false,youtube_privacy:'private',facebook_published:true}}>
    <Card className="publish-flow-card" title={<span><b>01</b> 视频与封面</span>}>
     <Form.Item label="可发布视频"><Select mode="multiple" value={selectedClips} onChange={changeClips} optionFilterProp="label" placeholder="选择内容工厂成品或使用右上角本地上传" options={readyClips.map(x=>({value:x.id,label:`${filename(x.file_path)}${x.template_name==='local_upload'?' · 本地上传':''}`}))}/></Form.Item>
     <div className="publish-cover-title"><PictureOutlined/><b>选择剧库封面</b><Button type="link" size="small" icon={<EditOutlined/>} onClick={()=>navigate('/dramas')}>管理封面</Button></div>
     {coverChoices.length
      ?<Radio.Group className="publish-cover-picker" value={coverKind} onChange={e=>setCoverKind(e.target.value)}>{coverChoices.map(item=><Radio.Button value={item.kind} key={item.kind}><Image preview={false} src={`/api/dramas/${drama?.id}/covers/${item.kind}`}/><span>{item.title}<small>{item.ratio}</small></span></Radio.Button>)}</Radio.Group>
      :<Alert type="warning" showIcon message="当前剧目还没有可用封面" action={<Button size="small" onClick={()=>navigate('/dramas')}>上传封面</Button>}/>
     }
     {!!selectedAccounts.length&&<Space wrap className="publish-cover-platforms">{platforms.has('youtube')&&<Tag color="green">YouTube 使用所选封面</Tag>}{platforms.has('tiktok')&&<Tag>TikTok 使用视频帧封面</Tag>}</Space>}
    </Card>

    <Card className="publish-flow-card" title={<span><b>02</b> 账号与生成规则</span>}>
     <Form.Item name="account_ids" label="发布账号" rules={[{required:true,message:'请选择账号'}]}><Select mode="multiple" optionFilterProp="label" onChange={changeAccounts} placeholder="选择一个或多个发布账号" options={connected.map(x=>({value:x.id,label:<PlatformOption platform={x.platform} label={x.name}/>}))}/></Form.Item>
     <div className="publish-rule-grid"><Form.Item label="文案参考"><Select allowClear value={strategyId} onChange={setStrategyId} placeholder="选择运营策略" options={strategies.filter(x=>x.confirmed).map(x=>({value:x.id,label:x.name}))}/></Form.Item><Form.Item label="目标语言"><Input value={language} onChange={e=>setLanguage(e.target.value)}/></Form.Item></div>
     <div className="publish-ai-context">
      <div className="publish-ai-context-item"><span>文案参考</span><div><b>{selectedStrategy?.name||'不使用历史样本'}</b>{selectedStrategy&&<Popover placement="bottomRight" title={selectedStrategy.name} content={<div className="publish-reference-preview">{selectedStrategy.history_text}</div>}><Button size="small" type="link">查看样本</Button></Popover>}</div><small>{selectedStrategy?`${selectedStrategy.history_text.length} 字`:'仅使用当前剧名、简介和视频内容'}</small></div>
      <div className="publish-ai-context-item"><span>剧场标签</span>{drama?.theater?<><div><b>{theaterTag(drama.theater)}</b><Switch size="small" checked={includeTheaterTag} onChange={setIncludeTheaterTag}/></div><small>{includeTheaterTag?'生成时自动加入':'本次不加入'}</small></>:<><div><b>未填写</b><Button size="small" type="link" onClick={()=>navigate(`/dramas/${drama?.id}`)}>去补充</Button></div><small>不影响 AI 撰写</small></>}</div>
     </div>
     <div className="publish-ai-actions"><Button type="primary" icon={<ThunderboltOutlined/>} loading={generating} disabled={Boolean(aiUnavailableReason)} onClick={generate}>AI 一键撰写</Button>{aiUnavailableReason&&<Typography.Text type="secondary">{aiUnavailableReason}</Typography.Text>}{provider&&<Tag color="green">{provider}</Tag>}</div>
    </Card>

    <Card className="publish-flow-card" title={<span><b>03</b> 发布内容</span>}>
     {selectedDrafts.length?<div className="publish-draft-list">{selectedDrafts.map((draft,index)=><Card size="small" key={draft.clipId} title={`${index+1}. ${filename(clips.find(x=>x.id===draft.clipId)?.file_path||'视频')}`} extra={draft.hitWords.map(x=><Tag color="red" key={x}>{x}</Tag>)}><div className="publish-draft-grid"><Form.Item label="标题" required><Input showCount maxLength={99} value={draft.title} onChange={e=>editDraft(draft.clipId,{title:e.target.value})} placeholder="输入发布标题"/></Form.Item><Form.Item label="标签"><Input value={draft.hashtags.join(' ')} onChange={e=>editDraft(draft.clipId,{hashtags:e.target.value.split(/[\s,]+/).filter(Boolean)})} placeholder="用空格分隔"/></Form.Item></div><Form.Item label="文案" required><Input.TextArea autoSize={{minRows:5,maxRows:14}} value={draft.caption} onChange={e=>editDraft(draft.clipId,{caption:e.target.value})} placeholder="输入视频文案"/></Form.Item><Form.Item label="首条评论"><Input.TextArea autoSize={{minRows:2,maxRows:5}} value={draft.firstComment} onChange={e=>editDraft(draft.clipId,{firstComment:e.target.value})} placeholder="发布后自动发送"/></Form.Item></Card>)}</div>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={readyClips.length?'请选择发布视频':'暂无可发布视频'}/>}
    </Card>

    <Card className="publish-flow-card" title={<span><b>04</b> 发布设置</span>}>
     <div className="publish-final-grid"><Form.Item label="发布时间"><Radio.Group value={mode} onChange={e=>setMode(e.target.value)} optionType="button" buttonStyle="solid" options={[{value:'now',label:'立即发布'},{value:'schedule',label:'定时发布'}]}/></Form.Item>{mode==='schedule'&&<Form.Item name="scheduled_at" label="计划时间" rules={[{required:true,message:'请选择时间'}]}><DatePicker showTime showNow disabledDate={date=>date.isBefore(dayjs().startOf('day'))}/></Form.Item>}<Form.Item name="ai_disclosure" label="AI 内容标注" valuePropName="checked"><Switch disabled={Boolean(drama?.is_ai_generated)}/></Form.Item></div>
     {platforms.size>0&&<div className="platform-settings">
      {platforms.has('youtube')&&<div className="platform-setting-row"><PlatformBadge platform="youtube" size={22}/><Form.Item name="youtube_privacy" label="可见性"><Select options={['private','unlisted','public'].map(x=>({value:x,label:x}))}/></Form.Item><Form.Item name="made_for_kids" label="儿童内容" valuePropName="checked"><Switch/></Form.Item></div>}
      {platforms.has('tiktok')&&<div className="platform-setting-block"><div className="platform-setting-row"><PlatformBadge platform="tiktok" size={22}/><Form.Item name="tiktok_privacy" label="可见性" rules={[{required:true}]}><Select options={tiktokPrivacy.map(x=>({value:x,label:x}))}/></Form.Item></div><Space wrap><Form.Item name="disable_comment" valuePropName="checked"><Checkbox>关闭评论</Checkbox></Form.Item><Form.Item name="disable_duet" valuePropName="checked"><Checkbox>关闭 Duet</Checkbox></Form.Item><Form.Item name="disable_stitch" valuePropName="checked"><Checkbox>关闭 Stitch</Checkbox></Form.Item></Space></div>}
      {platforms.has('facebook')&&<div className="platform-setting-row"><PlatformBadge platform="facebook" size={22}/><Form.Item name="facebook_published" label="立即公开" valuePropName="checked"><Switch/></Form.Item></div>}
      {platforms.has('instagram')&&<div className="platform-setting-block"><Space><PlatformBadge platform="instagram" size={22}/><b>Instagram 视频地址</b></Space>{selectedDrafts.map(draft=><Form.Item key={draft.clipId} name={`instagram_url_${draft.clipId}`} label={filename(clips.find(x=>x.id===draft.clipId)?.file_path||'视频')} rules={[{required:!integration?.public_media_ready},{type:'url',message:'请输入 HTTPS 地址'}]}><Input prefix={<LinkOutlined/>} placeholder={integration?.public_media_ready?'可留空，由系统生成':'https://cdn.example.com/video.mp4'}/></Form.Item>)}</div>}
     </div>}
     <Button size="large" block type="primary" htmlType="submit" loading={working} disabled={!selectedDrafts.length||!connected.length} icon={mode==='now'?<RocketOutlined/>:<CalendarOutlined/>}>{mode==='now'?'确认并发布':'确认定时任务'}</Button>
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
