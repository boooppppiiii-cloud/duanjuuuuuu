import {
 CalendarOutlined,CheckCircleOutlined,ClockCircleOutlined,EditOutlined,InboxOutlined,LinkOutlined,
 PictureOutlined,ReloadOutlined,RocketOutlined,SafetyCertificateOutlined,SyncOutlined,ThunderboltOutlined,
} from '@ant-design/icons'
import {
 Alert,Button,Card,Checkbox,DatePicker,Descriptions,Empty,Form,Image,Input,Modal,Radio,Segmented,Select,
 Space,Steps,Switch,Table,Tag,Typography,Upload,message,
} from 'antd'
import dayjs from 'dayjs'
import { useEffect,useMemo,useState } from 'react'
import { useNavigate,useSearchParams } from 'react-router-dom'
import { api,type Account,type AccountStrategy,type Clip,type Drama,type IntegrationConfig,type Post,type PublishJob,type TitleCandidate } from '../api'
import { PlatformBadge,PlatformOption } from '../components/PlatformBrand'

type CoverKind='vertical'|'square'|'horizontal'
type ContentDraft={clipId:number;title:string;caption:string;hashtags:string[];links:string;formula:number;hitWords:string[]}

const statusMeta:Record<string,{label:string;color:string}>={
 queued:{label:'等待排期',color:'blue'},uploading:{label:'正在上传',color:'processing'},submitted:{label:'平台处理中',color:'gold'},
 published:{label:'已发布',color:'success'},failed:{label:'失败',color:'error'},blocked:{label:'已阻止',color:'warning'},
}
const filename=(path:string)=>path.split(/[\\/]/).pop()||path
const preferredCover=(drama?:Drama):CoverKind|undefined=>drama?.cover_horizontal_path?'horizontal':drama?.cover_vertical_path?'vertical':drama?.cover_square_path?'square':undefined
const blankDraft=(clipId:number):ContentDraft=>({clipId,title:'',caption:'',hashtags:[],links:'',formula:1,hitWords:[]})

export default function Publish({embedded=false}:{embedded?:boolean}){
 const[params]=useSearchParams();const navigate=useNavigate()
 const[dramas,setDramas]=useState<Drama[]>([]);const[clips,setClips]=useState<Clip[]>([]);const[accounts,setAccounts]=useState<Account[]>([])
 const[strategies,setStrategies]=useState<AccountStrategy[]>([]);const[posts,setPosts]=useState<Post[]>([]);const[jobs,setJobs]=useState<PublishJob[]>([])
 const[integration,setIntegration]=useState<IntegrationConfig>();const[view,setView]=useState<'workflow'|'records'>('workflow')
 const[dramaId,setDramaId]=useState<number>();const[selectedClips,setSelectedClips]=useState<number[]>([]);const[selectedAccounts,setSelectedAccounts]=useState<number[]>([])
 const[strategyId,setStrategyId]=useState<number>();const[language,setLanguage]=useState('English');const[formula,setFormula]=useState<number|'auto'>('auto')
 const[drafts,setDrafts]=useState<ContentDraft[]>([]);const[provider,setProvider]=useState('');const[coverKind,setCoverKind]=useState<CoverKind>()
 const[mode,setMode]=useState<'now'|'schedule'>('now');const[generating,setGenerating]=useState(false);const[working,setWorking]=useState(false)
 const[uploading,setUploading]=useState(false);const[uploadPercent,setUploadPercent]=useState(0);const[checking,setChecking]=useState<number|null>(null)
 const[tiktokPrivacy,setTikTokPrivacy]=useState<string[]>([]);const[form]=Form.useForm();const[msg,ctx]=message.useMessage()

 const load=async()=>{
  const[d,c,a,s,p,j,i]=await Promise.all([api.list(),api.clips(),api.accounts(),api.strategies(),api.posts(),api.publishJobs(),api.integrationConfig()])
  setDramas(d);setClips(c);setAccounts(a);setStrategies(s);setPosts(p);setJobs(j);setIntegration(i)
  if(!dramaId){const requested=Number(params.get('drama'));const picked=d.find(x=>x.id===requested)||d[0];if(picked){setDramaId(picked.id);setCoverKind(preferredCover(picked));form.setFieldValue('ai_disclosure',picked.is_ai_generated)}}
 }
 useEffect(()=>{load().catch(e=>msg.error(e.message))},[])

 const drama=dramas.find(x=>x.id===dramaId)
 const readyClips=clips.filter(x=>x.drama_id===dramaId&&x.status==='approved')
 const connected=accounts.filter(x=>x.status==='connected')
 const selectedAccountRows=accounts.filter(x=>selectedAccounts.includes(x.id))
 const platforms=new Set(selectedAccountRows.map(x=>x.platform))
 const selectedDrafts=selectedClips.map(id=>drafts.find(x=>x.clipId===id)).filter(Boolean) as ContentDraft[]
 const selectedStrategy=strategies.find(x=>x.id===strategyId)
 const contentReady=selectedDrafts.length===selectedClips.length&&selectedDrafts.every(x=>x.title.trim()&&x.caption.trim())
 const currentStep=!selectedClips.length?0:!selectedAccounts.length?1:!contentReady?2:3
 const coverChoices=useMemo(()=>drama?[
  {kind:'vertical' as const,title:'竖版',ratio:'3:4',path:drama.cover_vertical_path},
  {kind:'square' as const,title:'方形',ratio:'1:1',path:drama.cover_square_path},
  {kind:'horizontal' as const,title:'横版',ratio:'16:9',path:drama.cover_horizontal_path},
 ].filter(x=>Boolean(x.path)):[],[drama])

 const changeDrama=(id:number)=>{const next=dramas.find(x=>x.id===id);setDramaId(id);setSelectedClips([]);setDrafts([]);setProvider('');setCoverKind(preferredCover(next));form.setFieldValue('ai_disclosure',Boolean(next?.is_ai_generated))}
 const changeClips=(ids:number[])=>{
  setSelectedClips(ids)
  setDrafts(rows=>ids.map(id=>rows.find(x=>x.clipId===id)||blankDraft(id)))
 }
 const changeAccounts=async(ids:number[])=>{
  setSelectedAccounts(ids);const first=accounts.find(x=>x.id===ids[0]);if(first?.strategy_id)setStrategyId(first.strategy_id)
  const tiktok=accounts.filter(x=>ids.includes(x.id)&&x.platform==='tiktok');if(!tiktok.length){setTikTokPrivacy([]);return}
  try{const info=await Promise.all(tiktok.map(x=>api.creatorInfo(x.id)));const available=info.map(x=>x.privacy_level_options).reduce((a,b)=>a.filter(x=>b.includes(x)));setTikTokPrivacy(available);if(available.length===1)form.setFieldValue('tiktok_privacy',available[0])}catch(e){setTikTokPrivacy([]);msg.error((e as Error).message)}
 }
 const uploadLocal=async(file:File)=>{
  if(!drama){msg.error('请先选择剧目');return}
  const before=new Set(clips.map(x=>x.id));setUploading(true);setUploadPercent(0)
  try{await api.uploadVideo(drama.title,'一键发布本地上传',file,setUploadPercent,'publish');const rows=await api.clips(drama.id);setClips(old=>[...old.filter(x=>x.drama_id!==drama.id),...rows]);const created=rows.filter(x=>!before.has(x.id)&&x.status==='approved').map(x=>x.id);const next=Array.from(new Set([...selectedClips,...created]));setSelectedClips(next);setDrafts(drafts=>next.map(id=>drafts.find(x=>x.clipId===id)||blankDraft(id)));msg.success('视频已加入可发布成品')}
  catch(e){msg.error((e as Error).message)}finally{setUploading(false);setUploadPercent(0)}
 }
 const generate=async()=>{
  const account=selectedAccountRows[0];if(!account||!selectedClips.length){msg.error('请先选择成品和账号');return}
  setGenerating(true)
  try{
   const results=await Promise.all(selectedClips.map(id=>api.generateTitles(id,account.account_type,language,formula,account.id,[],strategyId)))
   setDrafts(results.map((result,index)=>{const candidate=result.candidates.find(x=>!x.hit_words.length)||result.candidates[0];return{clipId:selectedClips[index],title:candidate.title,caption:candidate.caption,hashtags:candidate.hashtags,links:'',formula:candidate.formula,hitWords:candidate.hit_words}}))
   setProvider(Array.from(new Set(results.map(x=>x.provider))).join(' / '));msg.success(`已生成 ${results.length} 组可编辑内容`)
  }catch(e){msg.error((e as Error).message)}finally{setGenerating(false)}
 }
 const editDraft=(clipId:number,patch:Partial<ContentDraft>)=>setDrafts(rows=>rows.map(row=>row.clipId===clipId?{...row,...patch}:row))

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
    for(const draft of selectedDrafts){const caption=[draft.caption.trim(),draft.links.trim()].filter(Boolean).join('\n\n');const candidate:TitleCandidate={formula:draft.formula,title:draft.title.trim(),caption,hashtags:draft.hashtags,hit_words:draft.hitWords};created.push(await api.createPost(draft.clipId,accountType,candidate))}
    const options:Record<string,unknown>={cover_kind:coverKind,youtube_privacy:values.youtube_privacy||'private',made_for_kids:Boolean(values.made_for_kids),tiktok_privacy:values.tiktok_privacy,disable_duet:Boolean(values.disable_duet),disable_comment:Boolean(values.disable_comment),disable_stitch:Boolean(values.disable_stitch),facebook_published:values.facebook_published!==false,instagram_video_urls:Object.fromEntries(created.map((post,index)=>[String(post.id),values[`instagram_url_${selectedDrafts[index].clipId}`]||'']))}
    await api.batchPublish(created.map(x=>x.id),selectedAccounts,time,mode==='now',Boolean(values.ai_disclosure),options)
    setPosts(old=>[...created.reverse(),...old]);await load();setView('records');msg.success(mode==='now'?'已提交平台，正在任务记录中跟踪':'发布排期已保存')
   }catch(e){msg.error((e as Error).message);throw e}finally{setWorking(false)}
  }})
 }
 const run=async(id:number)=>{setChecking(id);try{const result=await api.runPublishJob(id);result.status==='failed'||result.status==='blocked'?msg.error(result.result_log):msg.success('任务已提交平台');await load()}catch(e){msg.error((e as Error).message)}finally{setChecking(null)}}
 const refresh=async(id:number)=>{setChecking(id);try{await api.refreshPublishJob(id);await load()}catch(e){msg.error((e as Error).message)}finally{setChecking(null)}}

 return <div className="workspace-page unified-publish">{ctx}
  <Segmented block className="overview-pager publishing-pager" value={view} onChange={v=>setView(v as typeof view)} options={[{label:'创建发布',value:'workflow',icon:<RocketOutlined/>},{label:'任务记录',value:'records',icon:<ClockCircleOutlined/>}]}/>
  {view==='workflow'?<>
   <Card className="publish-steps"><Steps current={currentStep} responsive={false} items={[{title:'选择视频'},{title:'账号与规则'},{title:'编辑内容'},{title:'确认发布'}]}/></Card>
   <Form form={form} layout="vertical" onFinish={submit} initialValues={{ai_disclosure:false,youtube_privacy:'private',facebook_published:true}}>
    <Card className="publish-flow-card" title={<span><b>01</b> 选择剧目文件与封面</span>}>
     <div className="publish-source-grid"><Form.Item label="剧目"><Select value={dramaId} onChange={changeDrama} options={dramas.map(x=>({value:x.id,label:x.title}))}/></Form.Item><Form.Item label="可发布视频"><Select mode="multiple" value={selectedClips} onChange={changeClips} optionFilterProp="label" placeholder="选择内容工厂成品" options={readyClips.map(x=>({value:x.id,label:`${filename(x.file_path)}${x.template_name==='local_upload'?' · 本地上传':''}`}))}/></Form.Item></div>
     <Upload accept="video/*,.mp4,.mov,.mkv,.webm" multiple showUploadList={false} beforeUpload={file=>{void uploadLocal(file);return Upload.LIST_IGNORE}} disabled={!drama||uploading}><Button icon={<InboxOutlined/>} loading={uploading}>从本地上传成品</Button></Upload>{uploading&&<Typography.Text type="secondary"> 上传中 {uploadPercent}%</Typography.Text>}
     <div className="publish-cover-title"><PictureOutlined/><b>选择剧库封面</b><Button type="link" size="small" icon={<EditOutlined/>} onClick={()=>navigate('/dramas')}>管理封面</Button></div>
     {coverChoices.length
      ?<Radio.Group className="publish-cover-picker" value={coverKind} onChange={e=>setCoverKind(e.target.value)}>{coverChoices.map(item=><Radio.Button value={item.kind} key={item.kind}><Image preview={false} src={`/api/dramas/${drama?.id}/covers/${item.kind}`}/><span>{item.title}<small>{item.ratio}</small></span></Radio.Button>)}</Radio.Group>
      :<Alert type="warning" showIcon message="当前剧目还没有可用封面" action={<Button size="small" onClick={()=>navigate('/dramas')}>上传封面</Button>}/>
     }
     {!!selectedAccounts.length&&<Space wrap className="publish-cover-platforms">{platforms.has('youtube')&&<Tag color="green">YouTube 使用所选封面</Tag>}{platforms.has('tiktok')&&<Tag>TikTok 使用视频帧封面</Tag>}</Space>}
    </Card>

    <Card className="publish-flow-card" title={<span><b>02</b> 账号与生成规则</span>}>
     <div className="publish-rule-grid"><Form.Item name="account_ids" label="发布账号" rules={[{required:true,message:'请选择账号'}]}><Select mode="multiple" optionFilterProp="label" onChange={changeAccounts} options={connected.map(x=>({value:x.id,label:<PlatformOption platform={x.platform} label={x.name}/>}))}/></Form.Item><Form.Item label="账号运营策略"><Select allowClear value={strategyId} onChange={setStrategyId} options={strategies.filter(x=>x.confirmed).map(x=>({value:x.id,label:x.name}))}/></Form.Item><Form.Item label="目标语言"><Input value={language} onChange={e=>setLanguage(e.target.value)}/></Form.Item><Form.Item label="标题公式"><Select value={formula} onChange={setFormula} options={[{value:'auto',label:'跟随账号策略'},...[1,2,3,4].map(x=>({value:x,label:`公式 ${x}`}))]}/></Form.Item></div>
     {selectedStrategy&&<Space wrap>{selectedStrategy.persona_keywords.map(x=><Tag key={x}>{x}</Tag>)}{selectedStrategy.tag_pool.slice(0,5).map(x=><Tag color="green" key={x}>{x}</Tag>)}</Space>}
     <Space wrap><Button icon={<EditOutlined/>} disabled={!selectedClips.length} onClick={()=>{setDrafts(rows=>selectedClips.map(id=>rows.find(x=>x.clipId===id)||blankDraft(id)));setProvider('');msg.success('已建立人工填写表单')}}>人工填写</Button><Button type="primary" icon={<ThunderboltOutlined/>} loading={generating} disabled={!selectedClips.length||!selectedAccounts.length} onClick={generate}>AI 一键生成全部标题和文案</Button>{provider&&<Tag color="green">{provider}</Tag>}</Space>
    </Card>

    <Card className="publish-flow-card" title={<span><b>03</b> 人工编辑发布内容</span>}>
     {selectedDrafts.length?<div className="publish-draft-list">{selectedDrafts.map((draft,index)=><Card size="small" key={draft.clipId} title={`${index+1}. ${filename(clips.find(x=>x.id===draft.clipId)?.file_path||'视频')}`} extra={draft.hitWords.map(x=><Tag color="red" key={x}>{x}</Tag>)}><div className="publish-draft-grid"><Form.Item label="标题" required><Input value={draft.title} onChange={e=>editDraft(draft.clipId,{title:e.target.value})} placeholder="直接填写发布标题"/></Form.Item><Form.Item label="标签"><Input value={draft.hashtags.join(' ')} onChange={e=>editDraft(draft.clipId,{hashtags:e.target.value.split(/[\s,]+/).filter(Boolean)})} placeholder="多个标签用空格分隔"/></Form.Item></div><Form.Item label="文案" required><Input.TextArea autoSize={{minRows:3,maxRows:8}} value={draft.caption} onChange={e=>editDraft(draft.clipId,{caption:e.target.value})} placeholder="直接填写发布文案"/></Form.Item><Form.Item label="引流链接 / 行动号召"><Input.TextArea autoSize={{minRows:2,maxRows:5}} value={draft.links} onChange={e=>editDraft(draft.clipId,{links:e.target.value})} placeholder="可加入落地页链接、{app_link} 或引导评论区话术"/></Form.Item></Card>)}</div>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="先选择视频，即可直接填写发布内容"/>}
    </Card>

    <Card className="publish-flow-card" title={<span><b>04</b> 发布设置与确认</span>}>
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
  </>:<Card className="table-card" title="任务记录" extra={<Button icon={<ReloadOutlined/>} onClick={()=>load()}>刷新</Button>} styles={{body:{padding:0}}}><Table rowKey="id" dataSource={jobs} scroll={{x:1180}} locale={{emptyText:<Empty description="暂无发布任务"/>}} columns={[
   {title:'任务',dataIndex:'id',width:75,render:(x:number)=>`#${x}`},{title:'账号',dataIndex:'account_id',width:180,render:(x:number)=>{const account=accounts.find(a=>a.id===x);return account?<Space size={7}><PlatformBadge platform={account.platform}/><span>{account.name}</span></Space>:`#${x}`}},
   {title:'内容',dataIndex:'post_id',width:250,ellipsis:true,render:(x:number)=>posts.find(p=>p.id===x)?.title||`#${x}`},{title:'计划时间',dataIndex:'scheduled_at',width:175,render:(x:string)=>new Date(x).toLocaleString()},
   {title:'状态',dataIndex:'status',width:125,render:(x:string)=>{const meta=statusMeta[x]||{label:x,color:'default'};return <Tag color={meta.color} icon={['uploading','submitted'].includes(x)?<SyncOutlined spin/>:undefined}>{meta.label}</Tag>}},{title:'平台链接',width:210,render:(_:unknown,row:PublishJob)=>row.platform_url?<a href={row.platform_url} target="_blank">打开平台</a>:'—'},
   {title:'结果',dataIndex:'result_log',ellipsis:true},{title:'操作',fixed:'right' as const,width:175,render:(_:unknown,row:PublishJob)=><Space><Button size="small" loading={checking===row.id} disabled={!['queued','failed','blocked'].includes(row.status)} onClick={()=>run(row.id)} icon={<CheckCircleOutlined/>}>{row.status==='queued'?'执行':'重试'}</Button><Button size="small" loading={checking===row.id} disabled={row.status!=='submitted'} onClick={()=>refresh(row.id)} icon={<SyncOutlined/>}>查状态</Button></Space>},
  ]}/></Card>}
 </div>
}
