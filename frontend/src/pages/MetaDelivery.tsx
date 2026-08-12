import { Alert,Button,Card,Form,Input,List,Progress,Select,Space,Steps,Switch,Table,Tag,Typography,message } from 'antd'
import { CheckCircleOutlined,EditOutlined,FolderOpenOutlined,SafetyCertificateOutlined } from '@ant-design/icons'
import { useEffect,useMemo,useState } from 'react'
import { useNavigate,useSearchParams } from 'react-router-dom'
import { api,type Drama,type MetaFactorySource,type MetaPackage,type MetaPreflight,type MetaSFSInput } from '../api'
import { PlatformLogo } from '../components/PlatformBrand'
import { localAssistantSupports,localAssistantUnavailable,localWorkspace as localClient,type LocalWorkspace } from '../localWorkspace'
import { showLocalAssistantInstallPrompt } from '../components/LocalAssistantPrompt'

const genres=['Action','Adventure','Animated','Comedy','Crime','Documentary','Drama','Family','Fantasy','Historical','Horror','Musical','Mystery','Noir','Reality','Romance','Science fiction','Sports','Thriller','Western']
const defaults={locale:'en_US',genres:['Drama'],release_date:new Date().toLocaleDateString('en-US',{month:'2-digit',day:'2-digit',year:'numeric'}),ai_content:false,dubbed_content:false}
const activePackageStatuses=new Set(['queued','building'])
const unavailablePackageStatuses=new Set(['queued','building','failed','missing'])
const formatSize=(bytes:number)=>bytes>=1024**3?`${(bytes/1024**3).toFixed(2)} GB`:bytes>=1024**2?`${(bytes/1024**2).toFixed(1)} MB`:`${Math.round(bytes/1024)} KB`
const packageProgress=(item?:MetaPackage)=>Math.max(0,Math.min(100,Number(item?.validation_json?.progress??(item?.status==='ready'?100:0))))
const packageStep=(item?:MetaPackage)=>String(item?.validation_json?.current_step|| (item?.status==='queued'?'等待本机处理':'正在生成'))
export default function MetaDelivery({embedded=false}:{embedded?:boolean}){
 const[dramas,setDramas]=useState<Drama[]>([])
 const[check,setCheck]=useState<MetaPreflight>()
 const[source,setSource]=useState<MetaFactorySource>()
 const[packages,setPackages]=useState<MetaPackage[]>([])
 const[localSource,setLocalSource]=useState<LocalWorkspace>()
 const[localStatus,setLocalStatus]=useState<'checking'|'ready'|'offline'|'outdated'|'error'|'none'>('checking')
 const[localIssue,setLocalIssue]=useState('')
 const[detectVersion,setDetectVersion]=useState(0)
 const[action,setAction]=useState<string|null>(null)
 const[exportProgress,setExportProgress]=useState<{label:string;percent:number}|null>(null)
 const[msg,ctx]=message.useMessage()
 const navigate=useNavigate()
 const[params]=useSearchParams()
 const[form]=Form.useForm()
 const dramaId=Form.useWatch('drama_id',form)
 const drama=dramas.find(item=>item.id===dramaId)
 const building=action!==null
 const activeForDrama=useMemo(()=>packages.find(item=>item.drama_id===dramaId&&activePackageStatuses.has(item.status)),[packages,dramaId])
 const liveProgress=exportProgress||(activeForDrama?{label:packageStep(activeForDrama),percent:packageProgress(activeForDrama)}:null)

 const syncTaskCovers=async(item:Drama,workspace:LocalWorkspace)=>{
   let current=workspace
   const candidates:[kind:'vertical'|'square'|'horizontal',available:boolean][]=[
     ['vertical',Boolean(item.cover_vertical_path)],['square',Boolean(item.cover_square_path)],['horizontal',Boolean(item.cover_horizontal_path)],
   ]
   for(const[kind,available]of candidates){
     if(!available||current.covers[kind])continue
     const response=await fetch(`/api/dramas/${item.id}/covers/${kind}`,{credentials:'include',cache:'no-store'})
     if(response.ok)current=await localClient.syncCover(item.id,kind,await response.blob())
   }
   return current
 }

 const load=async()=>{
   const items=await api.list();setDramas(items)
   const requested=Number(params.get('drama'))
   if(!form.getFieldValue('drama_id'))form.setFieldValue('drama_id',items.some(item=>item.id===requested)?requested:items[0]?.id)
 }
 useEffect(()=>{load().catch(error=>msg.error(error.message))},[])
 useEffect(()=>{
   if(!packages.some(item=>activePackageStatuses.has(item.status)))return
   const timer=window.setInterval(()=>localClient.metaPackages().then(setPackages).catch(()=>undefined),1500)
   return()=>window.clearInterval(timer)
 },[packages.some(item=>activePackageStatuses.has(item.status))])
 useEffect(()=>{
   if(!drama)return
   form.setFieldsValue({description:drama.description,genres:drama.genres,ai_content:drama.is_ai_generated,dubbed_content:drama.is_dubbed_content,locale:drama.language||'en_US'})
 },[drama?.id])
 useEffect(()=>{
   setCheck(undefined);setSource(undefined);setLocalSource(undefined);setExportProgress(null);setLocalIssue('')
   if(!dramaId||!drama){setPackages([]);setLocalStatus('none');return}
   let stopped=false
   const detect=async()=>{
     setLocalStatus('checking')
     let health
     try{health=await localClient.health()}catch(error){
       if(!stopped){setLocalStatus(localAssistantUnavailable(error)?'offline':'error');setPackages([]);setLocalIssue(localAssistantUnavailable(error)?'未检测到正在运行的本地助手':`本地助手响应异常：${(error as Error).message}`)}
       return
     }
     if(!localAssistantSupports(health,'meta_direct_local_v2')){
       if(!stopped){setLocalStatus('outdated');setPackages([]);setLocalIssue('当前本地助手版本过旧，需要更新后使用 Meta 官方投递')}
       return
     }
     if(!stopped)setLocalStatus('none')
     let items:MetaPackage[]=[]
     try{items=await localClient.metaPackages()}catch(error){if(!stopped)setLocalIssue(`投递记录读取失败：${(error as Error).message}`)}
     if(!stopped)setPackages(items)
     let workspace:LocalWorkspace
     try{workspace=await localClient.get(dramaId)}catch(error){
       if(!stopped&&!((error as Error).message.includes('尚未连接')))setLocalIssue(`本机剧目读取失败：${(error as Error).message}`)
       return
     }
     if(!stopped){setLocalSource(workspace);setLocalStatus('ready')}
     try{
       workspace=await syncTaskCovers(drama,workspace)
       if(!stopped)setLocalSource(workspace)
     }catch(error){if(!stopped)setLocalIssue(`封面同步失败：${(error as Error).message}`)}
     try{
       const delivery=await localClient.metaFactorySource(dramaId)
       if(!stopped)setSource(delivery)
     }catch(error){if(!stopped)setLocalIssue(`Meta 成品读取失败：${(error as Error).message}`)}
   }
   detect().catch(error=>{if(!stopped)msg.error(error.message)})
   return()=>{stopped=true}
 },[dramaId,detectVersion])

 const showLocalWorkspaceHelp=(mode:'install'|'update'='install')=>showLocalAssistantInstallPrompt({mode})
 const connectLocalSource=async()=>{
   if(!drama)return
   setAction('connecting');setLocalStatus('checking')
   try{
     msg.loading({key:'local-access',content:'正在连接本地助手；若浏览器询问本地网络访问，请点“允许”',duration:0})
     let health
     try{health=await localClient.requestAccess()}catch(error){
       msg.destroy('local-access')
       if(localAssistantUnavailable(error)){setLocalStatus('offline');showLocalWorkspaceHelp()}
       else{setLocalStatus('error');setLocalIssue(`本地助手响应异常：${(error as Error).message}`);msg.error((error as Error).message)}
       return
     }
     if(!localAssistantSupports(health,'meta_direct_local_v2')){msg.destroy('local-access');setLocalStatus('outdated');showLocalWorkspaceHelp('update');return}
     msg.destroy('local-access')
     const selected=await syncTaskCovers(drama,await localClient.select(drama))
     setLocalSource(selected);setLocalStatus('ready');setCheck(undefined)
     api.registerLocalSourceManifest(drama.id,{folder_name:selected.folder_name,file_count:selected.file_count,total_bytes:selected.total_bytes,filenames:selected.files.map(file=>file.relative_path)}).catch(()=>undefined)
     const[delivery,items]=await Promise.all([localClient.metaFactorySource(drama.id),localClient.metaPackages()])
     setSource(delivery);setPackages(items)
     msg.success(`已连接“${selected.folder_name}”，视频只在这台电脑读取`)
   }catch(error){
     msg.destroy('local-access')
     const text=(error as Error).message
     if(localAssistantUnavailable(error)){setLocalStatus('offline');showLocalWorkspaceHelp()}
     else if(!text.includes('取消选择'))msg.error(text)
   }finally{setAction(null)}
 }
 const body=(values:any):MetaSFSInput=>({drama_id:values.drama_id,series_slug:String(values.series_slug||'').trim(),description:values.description,locale:values.locale,genres:values.genres,release_date:values.release_date,cast_list:[],tags:[],geogating:[],ai_content:Boolean(values.ai_content),dubbed_content:Boolean(values.dubbed_content),include_episode_csv:false,include_thumbnails:false})
 const rememberPackage=(item:MetaPackage)=>setPackages(old=>[item,...old.filter(row=>row.id!==item.id)])
 const waitForPackage=async(id:number)=>{
   while(true){
     await new Promise(resolve=>window.setTimeout(resolve,1200))
     const item=await localClient.metaPackage(id);rememberPackage(item)
     setExportProgress({label:packageStep(item),percent:packageProgress(item)})
     if(!activePackageStatuses.has(item.status))return item
   }
 }
 const cancelled=(error:unknown)=>(error instanceof DOMException&&error.name==='AbortError')||(error instanceof Error&&error.message.includes('已取消选择保存位置'))
 const chooseAndBuild=async()=>{
   let queued:MetaPackage|undefined
   try{
     if(localStatus==='offline'){showLocalWorkspaceHelp();return}
     if(localStatus==='outdated'){showLocalWorkspaceHelp('update');return}
     if(!localSource||!source?.ready)throw new Error('请先连接本地文件夹，并在内容工厂完成 Meta 逐集切分')
     const values=await form.validateFields()
     setAction('selecting');setCheck(undefined);setExportProgress({label:'请选择这台电脑上的保存位置',percent:0})
     const destination=await localClient.selectMetaOutputDirectory()
     setAction('build');setExportProgress({label:'正在本机校验素材与 Meta 必填信息',percent:1})
     const result=await localClient.metaPreflight(body(values));setCheck(result)
     if(!result.ready){msg.warning(`发现 ${result.blockers.length} 个必须处理的问题`);return}
     if(!values.series_slug)form.setFieldValue('series_slug',result.series_slug)
     queued=await localClient.buildMetaPackage({...body(values),series_slug:result.series_slug,local_destination_token:destination.token})
     rememberPackage(queued)
     const completed=await waitForPackage(queued.id)
     if(completed.status==='failed')throw new Error(completed.last_error||'Meta 合规文件夹生成失败')
     if(completed.status!=='ready')throw new Error(completed.status==='missing'?'本机生成记录存在，但文件夹已移动或删除':`生成任务状态异常：${completed.status}`)
     setExportProgress({label:'已完成并通过 Meta 规范终检',percent:100})
     msg.success(`Meta 合规文件夹已直接生成到 ${completed.output_dir}`)
     setPackages(await localClient.metaPackages())
   }catch(error){
     if(queued)localClient.metaPackages().then(setPackages).catch(()=>undefined)
     if(!cancelled(error))msg.error((error as Error).message)
   }finally{
     window.setTimeout(()=>setExportProgress(null),800)
     setAction(null)
   }
 }
 const openExisting=async(item:MetaPackage)=>{
   try{const result=await localClient.openMetaPackageFolder(item.id);msg.success(`已打开 ${result.path}`)}catch(error){msg.error((error as Error).message)}
 }

 return <div className={embedded?'meta-delivery':'workspace-page meta-delivery'}>{ctx}
  {!embedded&&<div className="page-heading"><Typography.Title level={2}><Space><PlatformLogo platform="meta" size={27}/><span>官方投递</span></Space></Typography.Title></div>}
  <div className="module-toolbar"><Space><PlatformLogo platform="meta" size={22}/><b>官方投递</b><Tag icon={<SafetyCertificateOutlined/>} color="green">v260626</Tag><Tag color="green">全程生成到本机</Tag></Space></div>
  <Steps size="small" current={check?.ready?2:source?.ready?1:0} className="meta-steps" items={[{title:'选择本机素材或成品'},{title:'自动命名与严格校验'},{title:'直接生成到本机'}]}/>
  <Form form={form} layout="vertical" initialValues={defaults}><div className="split-workbench meta-workbench"><Card title="1. 选择本机素材或内容工厂成品">
    <Form.Item name="drama_id" label="剧目任务" rules={[{required:true,message:'请选择剧目任务'}]}><Select showSearch optionFilterProp="label" options={dramas.map(item=>({value:item.id,label:`${item.title} · 全集 ${item.total_episode_count}`}))}/></Form.Item>
    {drama&&<Space wrap style={{marginBottom:12}}><Button type="primary" icon={<FolderOpenOutlined/>} loading={action==='connecting'||localStatus==='checking'} disabled={(building&&action!=='connecting')||localStatus==='outdated'||localStatus==='error'} onClick={connectLocalSource}>{localSource?'更换本地文件夹':'选择本地文件夹'}</Button>{localStatus==='offline'&&<Button onClick={()=>showLocalWorkspaceHelp()}>安装本地助手</Button>}{localStatus==='outdated'&&<Button onClick={()=>showLocalWorkspaceHelp('update')}>更新本地助手</Button>}{localStatus==='error'&&<Button onClick={()=>setDetectVersion(value=>value+1)}>重新检测</Button>}</Space>}
    {localIssue&&<Alert type={localStatus==='offline'||localStatus==='outdated'||localStatus==='error'?'warning':'info'} showIcon message={localIssue} style={{marginBottom:12}}/>}
    {localSource&&<Alert type="success" showIcon message={`本机文件夹：${localSource.folder_name}`} description={<Space direction="vertical" size={0}><Typography.Text ellipsis={{tooltip:localSource.absolute_path}}>{localSource.absolute_path}</Typography.Text><Typography.Text type="secondary">{localSource.file_count} 个视频 · {formatSize(localSource.total_bytes)} · 竖版封面 {localSource.covers.vertical?'已就绪':'缺少'} · 方形封面 {localSource.covers.square?'已就绪':'缺少'}</Typography.Text></Space>} style={{marginBottom:12}}/>}
    {drama&&<Space wrap className="meta-drama-tags"><Tag color={localSource?'green':'default'}>{localSource?'本机工作区':'尚未连接本机'}</Tag><Tag>源文件 {localSource?.file_count??0} 集</Tag><Tag color={source?.ready?'green':'default'}>可投递 {source?.episode_count??0} 集</Tag><Tag color={localSource?.covers.vertical?'green':'red'}>竖版封面</Tag><Tag color={localSource?.covers.square?'green':'red'}>方形封面</Tag>{Boolean(localSource?.covers.horizontal)&&<Tag color="green">横版封面</Tag>}<Button type="link" size="small" icon={<EditOutlined/>} onClick={()=>navigate(`/dramas/${drama.id}`)}>编辑剧目</Button></Space>}
    {drama&&(source?.ready?<Alert type="success" showIcon message={`已从本机读取 ${source.episode_count} 个${source.source_mode==='factory_meta_split'?'内容工厂 Meta 单集':'视频文件'}`} description={<Typography.Text ellipsis={{tooltip:source.files.join('、')}}>{source.files.join('、')}</Typography.Text>}/>:<Alert type="warning" showIcon message={localStatus==='offline'?'本地助手未连接':localStatus==='outdated'?'本地助手需要更新':'尚无本机可投递视频'} description={<Space><span>{localStatus==='offline'||localStatus==='outdated'?'处理本地助手后重新检测，或':'选择本地素材文件夹，或'}</span><Button type="link" onClick={()=>navigate(`/factory?drama=${drama.id}`)}>前往内容工厂生成 Meta 逐集切分</Button></Space>}/>) }
  </Card>
  <Card title="2. Meta 必填信息">
    <Form.Item name="series_slug" label="英文文件夹名（可留空自动生成）"><Input placeholder="例如 boss-like-me"/></Form.Item>
    <Form.Item name="description" label="剧情简介（来自剧目任务）" rules={[{required:true,message:'Meta 要求填写系列简介'}]}><Input.TextArea rows={3} disabled={Boolean(drama?.description)}/></Form.Item>
    <div className="form-grid"><Form.Item name="locale" label="语种代码" rules={[{required:true,pattern:/^[a-z]{2}_[A-Z]{2}$/,message:'例如 en_US'}]}><Input/></Form.Item><Form.Item name="release_date" label="首发日期 MM/DD/YYYY" rules={[{required:true}]}><Input/></Form.Item></div>
    <Form.Item name="genres" label="题材分类（来自剧目任务）" rules={[{required:true}]}><Select mode="multiple" disabled={Boolean(drama?.genres.length)} options={genres.map(item=>({value:item,label:item}))}/></Form.Item>
    <Space size="large" wrap><Form.Item name="ai_content" valuePropName="checked" label="AI 标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item><Form.Item name="dubbed_content" valuePropName="checked" label="配音标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item></Space>
    <Button block size="large" type="primary" loading={action==='build'||action==='selecting'||Boolean(activeForDrama)} disabled={building||Boolean(activeForDrama)||!drama||!source?.ready||!localSource} icon={<FolderOpenOutlined/>} onClick={chooseAndBuild}>{activeForDrama?'本机正在生成':'选择本机位置并生成'}</Button>
    {liveProgress&&<div className="meta-build-status"><Space direction="vertical" size={6} style={{width:'100%'}}><Typography.Text>{liveProgress.label}</Typography.Text><Progress percent={liveProgress.percent} status={activeForDrama||action==='build'?'active':'normal'}/></Space></div>}
  </Card></div></Form>

  {check&&<Card title="校验结果" className="validation-card"><Alert type={check.ready?'success':'error'} showIcon message={check.ready?'文件符合投递要求':'需要处理后再生成'} description={check.blockers.length?<ul>{check.blockers.map(item=><li key={item}>{item}</li>)}</ul>:`共 ${check.episode_count} 集，文件名统一为 ${check.series_slug}_epXXX_${String(check.episode_count).padStart(3,'0')}.mp4`}/>{check.automatic_fixes.length>0&&<List size="small" dataSource={check.automatic_fixes} renderItem={item=><List.Item><CheckCircleOutlined className="ok-icon"/> {item}</List.Item>}/>}</Card>}

  <Card title="3. 本机已生成文件夹" className="table-card">{packages.length?<Table rowKey="id" dataSource={packages} pagination={false} scroll={{x:760}} columns={[
    {title:'剧目',render:(_,row)=>dramas.find(item=>item.id===row.drama_id)?.title||row.series_slug},
    {title:'文件夹名',dataIndex:'series_slug'},
    {title:'状态',width:220,render:(_,row)=>activePackageStatuses.has(row.status)?<div><Tag color="processing">本机生成中</Tag><Progress percent={packageProgress(row)} size="small" showInfo={false}/><Typography.Text type="secondary">{packageStep(row)}</Typography.Text></div>:row.status==='failed'?<Typography.Text type="danger" ellipsis={{tooltip:row.last_error}}>生成失败</Typography.Text>:row.status==='missing'?<Tag color="red">本机文件夹已移动或删除</Tag>:<Tag color="green">本机已生成</Tag>},
    {title:'生成时间',width:180,dataIndex:'created_at',render:(value:string)=>new Date(value).toLocaleString()},
    {title:'本机位置',dataIndex:'output_dir',render:(value:string)=><Typography.Text ellipsis={{tooltip:value}} copyable={Boolean(value)}>{value||'生成完成后显示'}</Typography.Text>},
    {title:'查看',width:130,render:(_,row)=><Button size="small" type="primary" icon={<FolderOpenOutlined/>} disabled={unavailablePackageStatuses.has(row.status)||building} onClick={()=>openExisting(row)}>打开文件夹</Button>},
    {title:'下一步',width:150,render:()=> <Button type="primary" icon={<PlatformLogo platform="instagram" size={15}/>} href="https://www.instagram.com/sfs_tools" target="_blank">打开 SFS Tools</Button>},
  ]}/>:<Alert type="info" showIcon message="生成时选择电脑上的保存位置，完成后文件夹会直接出现在该位置"/>}</Card>
 </div>
}
