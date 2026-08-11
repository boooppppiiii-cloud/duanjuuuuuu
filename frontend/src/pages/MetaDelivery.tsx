import { Alert,Button,Card,Form,Input,List,Modal,Progress,Select,Space,Steps,Switch,Table,Tag,Typography,message } from 'antd'
import { CheckCircleOutlined,EditOutlined,FolderOpenOutlined,SafetyCertificateOutlined } from '@ant-design/icons'
import { useEffect,useState } from 'react'
import { useNavigate,useSearchParams } from 'react-router-dom'
import { api,type Drama,type MetaFactorySource,type MetaPackage,type MetaPreflight,type MetaSFSInput } from '../api'
import { PlatformLogo } from '../components/PlatformBrand'
import { localWorkspace as localClient,type LocalWorkspace } from '../localWorkspace'

const genres=['Action','Adventure','Animated','Comedy','Crime','Documentary','Drama','Family','Fantasy','Historical','Horror','Musical','Mystery','Noir','Reality','Romance','Science fiction','Sports','Thriller','Western']
const defaults={locale:'en_US',genres:['Drama'],release_date:new Date().toLocaleDateString('en-US',{month:'2-digit',day:'2-digit',year:'numeric'}),ai_content:false,dubbed_content:false}
type LocalWritable={write:(data:Uint8Array|Blob)=>Promise<void>;close:()=>Promise<void>;abort:()=>Promise<void>}
type LocalFileHandle={createWritable:()=>Promise<LocalWritable>}
type LocalDirectoryHandle={name:string;getDirectoryHandle:(name:string,options:{create:boolean})=>Promise<LocalDirectoryHandle>;getFileHandle:(name:string,options:{create:boolean})=>Promise<LocalFileHandle>}
type DirectoryPickerWindow=Window&{showDirectoryPicker?:(options:{mode:'readwrite'})=>Promise<LocalDirectoryHandle>}
type OutputDestination={kind:'browser';handle:LocalDirectoryHandle}|{kind:'server';token:string;name:string}|{kind:'download'}
const activePackageStatuses=new Set(['queued','building'])
const unavailablePackageStatuses=new Set(['queued','building','failed','missing'])
const formatSize=(bytes:number)=>bytes>=1024**3?`${(bytes/1024**3).toFixed(2)} GB`:bytes>=1024**2?`${(bytes/1024**2).toFixed(1)} MB`:`${Math.round(bytes/1024)} KB`

export default function MetaDelivery({embedded=false}:{embedded?:boolean}){
 const[dramas,setDramas]=useState<Drama[]>([])
 const[check,setCheck]=useState<MetaPreflight>()
 const[source,setSource]=useState<MetaFactorySource>()
 const[packages,setPackages]=useState<MetaPackage[]>([])
 const[localSource,setLocalSource]=useState<LocalWorkspace>()
 const[localStatus,setLocalStatus]=useState<'checking'|'ready'|'offline'|'none'>('checking')
 const[action,setAction]=useState<string|null>(null)
 const[exportProgress,setExportProgress]=useState<{label:string;percent:number}|null>(null)
 const[msg,ctx]=message.useMessage()
 const navigate=useNavigate()
 const[params]=useSearchParams()
 const[form]=Form.useForm()
 const dramaId=Form.useWatch('drama_id',form)
 const drama=dramas.find(x=>x.id===dramaId)
 const usingLocal=Boolean(localSource)
 const building=action!==null
 const pendingForDrama=packages.some(item=>item.drama_id===dramaId&&activePackageStatuses.has(item.status))
 const localRuntime=['localhost','127.0.0.1','::1'].includes(window.location.hostname)
 const directFolderSave=window.isSecureContext&&Boolean((window as DirectoryPickerWindow).showDirectoryPicker)

 const chooseOutputDirectory=async()=>{
   if(usingLocal){const selected=await localClient.selectMetaOutputDirectory();return {kind:'server',...selected} satisfies OutputDestination}
   if(localRuntime){const selected=await api.selectMetaOutputDirectory();return {kind:'server',...selected} satisfies OutputDestination}
   const picker=(window as DirectoryPickerWindow).showDirectoryPicker
   if(window.isSecureContext&&picker)return {kind:'browser',handle:await picker.call(window,{mode:'readwrite'})} satisfies OutputDestination
   return {kind:'download'} satisfies OutputDestination
 }
 const downloadPackage=(item:MetaPackage)=>{
   const link=document.createElement('a')
   link.href=usingLocal?localClient.metaPackageArchiveUrl(item.id):api.metaPackageArchiveUrl(item.id)
   link.download=`${item.series_slug}.zip`
   document.body.appendChild(link);link.click();link.remove()
   return '本机下载目录'
 }
 const savePackageToDirectory=async(item:MetaPackage,destination:LocalDirectoryHandle)=>{
   const manifest=usingLocal?await localClient.metaPackageFiles(item.id):await api.metaPackageFiles(item.id)
   const root=await destination.getDirectoryHandle(manifest.folder_name,{create:true})
   let written=0,lastPercent=-1
   for(const entry of manifest.files){
     const parts=entry.path.split('/').filter(Boolean)
     const filename=parts.pop()
     if(!filename)continue
     let folder=root
     for(const part of parts)folder=await folder.getDirectoryHandle(part,{create:true})
     const response=await fetch(usingLocal?localClient.metaPackageFileUrl(item.id,entry.path):api.metaPackageFileUrl(item.id,entry.path))
     if(!response.ok)throw new Error(`读取生成文件失败：${entry.path}`)
     const handle=await folder.getFileHandle(filename,{create:true})
     const writable=await handle.createWritable()
     try{
       if(response.body){
         const reader=response.body.getReader()
         while(true){
           const{done,value}=await reader.read()
           if(done)break
           await writable.write(value)
           written+=value.byteLength
           const percent=Math.min(100,Math.round(written/Math.max(manifest.total_bytes,1)*100))
           if(percent!==lastPercent){lastPercent=percent;setExportProgress({label:entry.path,percent})}
         }
       }else{
         const blob=await response.blob();await writable.write(blob);written+=blob.size
       }
       await writable.close()
     }catch(error){
       await writable.abort().catch(()=>undefined)
       throw error
     }
   }
   setExportProgress({label:manifest.folder_name,percent:100})
   return `${destination.name}\\${manifest.folder_name}`
 }
 const cancelled=(error:unknown)=>(error instanceof DOMException&&error.name==='AbortError')||(error instanceof Error&&error.message.includes('已取消选择保存位置'))

 const load=async()=>{const d=await api.list();setDramas(d);const requested=Number(params.get('drama'));if(!form.getFieldValue('drama_id'))form.setFieldValue('drama_id',d.some(item=>item.id===requested)?requested:d[0]?.id)}
 useEffect(()=>{load().catch(e=>msg.error(e.message))},[])
 useEffect(()=>{
   if(!packages.some(item=>activePackageStatuses.has(item.status)))return
   const timer=window.setInterval(()=>{const request=usingLocal?localClient.metaPackages():api.metaPackages();request.then(setPackages).catch(()=>undefined)},2000)
   return()=>window.clearInterval(timer)
 },[packages.some(item=>activePackageStatuses.has(item.status)),usingLocal])
 useEffect(()=>{if(!drama)return;form.setFieldsValue({description:drama.description,genres:drama.genres,ai_content:drama.is_ai_generated,dubbed_content:drama.is_dubbed_content,locale:drama.language||'en_US'})},[drama?.id])
 useEffect(()=>{
   setCheck(undefined);setSource(undefined);setLocalSource(undefined)
   if(!dramaId){setPackages([]);setLocalStatus('none');return}
   let cancelled=false
   const detect=async()=>{
     setLocalStatus('checking')
     try{
       await localClient.health()
       try{
         const workspace=await localClient.get(dramaId)
         const[src,items]=await Promise.all([localClient.metaFactorySource(dramaId),localClient.metaPackages()])
         if(!cancelled){setLocalSource(workspace);setLocalStatus('ready');setSource(src);setPackages(items)}
         return
       }catch(error){if((error as Error).message.includes('尚未连接'))setLocalStatus('none');else throw error}
     }catch{if(!cancelled)setLocalStatus('offline')}
     const[src,items]=await Promise.all([api.metaFactorySource(dramaId),api.metaPackages()])
     if(!cancelled){setSource(src);setPackages(items)}
   }
   detect().catch(error=>{if(!cancelled)msg.error(error.message)})
   return()=>{cancelled=true}
 },[dramaId])
 const showLocalWorkspaceHelp=()=>Modal.info({title:'无法连接本地助手',okText:'知道了',content:<div className="local-workspace-help"><p>首次使用时，请在浏览器地址栏旁的提示中允许“本地网络访问”。如果之前点过拒绝，请打开本站权限并重新允许。</p><p>同时确认本机已经运行 <b>start-local-workspace.bat</b>，然后再次点击“选择本地文件夹”。</p><p>源视频只保存在这台电脑，不会上传服务器。</p></div>})
 const connectLocalSource=async()=>{if(!drama)return;setAction('connecting');setLocalStatus('checking');try{
   msg.loading({key:'local-access',content:'正在连接本地助手；若浏览器询问本地网络访问，请点“允许”',duration:0})
   try{await localClient.requestAccess()}catch{msg.destroy('local-access');setLocalStatus('offline');showLocalWorkspaceHelp();return}
   msg.destroy('local-access')
   setLocalStatus('ready')
   const selected=await localClient.select(drama)
   setLocalSource(selected);setLocalStatus('ready');setCheck(undefined)
   api.registerLocalSourceManifest(drama.id,{folder_name:selected.folder_name,file_count:selected.file_count,total_bytes:selected.total_bytes,filenames:selected.files.map(file=>file.relative_path)}).catch(()=>undefined)
   const[src,items]=await Promise.all([localClient.metaFactorySource(drama.id),localClient.metaPackages()]);setSource(src);setPackages(items)
   msg.success(`已连接“${selected.folder_name}”，共 ${selected.file_count} 个视频；文件未上传服务器`)
 }catch(e){msg.destroy('local-access');const text=(e as Error).message;if(text.includes('未检测到本地工作区')||text.includes('未启动')||text.includes('响应超时')){setLocalStatus('offline');showLocalWorkspaceHelp()}else if(!text.includes('取消选择'))msg.error(text)}finally{setAction(null)}}
 const body=(values:any):MetaSFSInput=>({drama_id:values.drama_id,series_slug:String(values.series_slug||'').trim(),description:values.description,locale:values.locale,genres:values.genres,release_date:values.release_date,cast_list:[],tags:[],geogating:[],ai_content:Boolean(values.ai_content),dubbed_content:Boolean(values.dubbed_content),include_episode_csv:false,include_thumbnails:false})
 const rememberPackage=(item:MetaPackage)=>setPackages(old=>[item,...old.filter(row=>row.id!==item.id)])
 const waitForPackage=async(id:number)=>{
   while(true){
     await new Promise(resolve=>window.setTimeout(resolve,1500))
     const item=usingLocal?await localClient.metaPackage(id):await api.metaPackage(id);rememberPackage(item)
     if(!activePackageStatuses.has(item.status))return item
   }
 }
 const build=async(destination:OutputDestination)=>{let serverReady=false;let queued:MetaPackage|undefined;try{
   const values=await form.validateFields()
   if(!source?.ready)throw new Error('请先选择本地素材文件夹，或在内容工厂生成 Meta 逐集切分成品')
   setAction('build');setCheck(undefined);setExportProgress(null)
   const result=usingLocal?await localClient.metaPreflight(body(values)):await api.metaPreflight(body(values));setCheck(result)
   if(!result.ready){msg.warning(`发现 ${result.blockers.length} 个必须处理的问题`);return}
   if(!values.series_slug)form.setFieldValue('series_slug',result.series_slug)
   const request={...body(values),series_slug:result.series_slug,local_destination_token:destination.kind==='server'?destination.token:''}
   queued=usingLocal?await localClient.buildMetaPackage(request):await api.buildMetaPackage(request)
   rememberPackage(queued);setExportProgress({label:usingLocal?'本机正在生成 Meta 合规文件夹':'服务器正在后台生成 Meta 合规文件夹',percent:0})
   if(destination.kind==='server'){
     msg.success(`任务 #${queued.id} 已登记，将在后台校验并生成到所选文件夹；现在可以离开本页`)
     return
   }
   const item=await waitForPackage(queued.id)
   if(item.status==='failed')throw new Error(item.last_error||'Meta 合规文件夹生成失败')
   if(item.status!=='ready')throw new Error(item.status==='missing'?'生成记录存在，但文件夹未找到':`生成任务状态异常：${item.status}`)
   serverReady=true
   const savedPath=destination.kind==='browser'?await savePackageToDirectory(item,destination.handle):destination.kind==='download'?downloadPackage(item):item.output_dir
   msg.success(`合规文件夹已保存到 ${savedPath}`);setPackages(await (usingLocal?localClient.metaPackages():api.metaPackages()))
 }catch(e){
   if(queued)(usingLocal?localClient.metaPackages():api.metaPackages()).then(setPackages).catch(()=>undefined)
   if(!cancelled(e))msg.error(serverReady?`${usingLocal?'本机':'服务器'}文件夹已生成，但保存到所选位置失败：${(e as Error).message}`:(e as Error).message)
 }finally{setAction(null);setExportProgress(null)}}
 const chooseAndBuild=async()=>{try{setAction('selecting');const destination=await chooseOutputDirectory();setAction(null);await build(destination)}catch(e){if(!cancelled(e))msg.error((e as Error).message);setAction(null)}}
 const saveExisting=async(item:MetaPackage)=>{try{
   setAction(`selecting-${item.id}`);const destination=await chooseOutputDirectory();setAction(`export-${item.id}`);setExportProgress(null)
   const savedPath=destination.kind==='browser'?await savePackageToDirectory(item,destination.handle):destination.kind==='download'?downloadPackage(item):(usingLocal?await localClient.copyMetaPackageLocal(item.id,destination.token):await api.copyMetaPackageLocal(item.id,destination.token)).path
   msg.success(`已保存到 ${savedPath}`)
 }catch(e){if(!cancelled(e))msg.error((e as Error).message)}finally{setAction(null);setExportProgress(null)}}
 const openExisting=async(item:MetaPackage)=>{try{const result=usingLocal?await localClient.openMetaPackageFolder(item.id):await api.openMetaPackageFolder(item.id);msg.success(`已打开 ${result.path}`)}catch(e){msg.error((e as Error).message)}}

 return <div className={embedded?'meta-delivery':'workspace-page meta-delivery'}>{ctx}
  {!embedded&&<div className="page-heading"><Typography.Title level={2}><Space><PlatformLogo platform="meta" size={27}/><span>官方投递</span></Space></Typography.Title></div>}
  <div className="module-toolbar"><Space><PlatformLogo platform="meta" size={22}/><b>官方投递</b><Tag icon={<SafetyCertificateOutlined/>} color="green">v260626</Tag><Tag>{directFolderSave||localRuntime?'保存到本机文件夹':'保存为本机 ZIP'}</Tag></Space></div>
  <Steps size="small" current={check?.ready?2:source?.ready?1:0} className="meta-steps" items={[{title:'选择本地素材或成品'},{title:'自动命名与校验'},{title:'生成上传文件夹'}]}/>
  <Form form={form} layout="vertical" initialValues={defaults}><div className="split-workbench meta-workbench"><Card title="1. 选择本地素材或内容工厂成品">
    <Form.Item name="drama_id" label="剧目任务" rules={[{required:true,message:'请选择剧目任务'}]}><Select showSearch optionFilterProp="label" options={dramas.map(x=>({value:x.id,label:`${x.title} · 全集 ${x.total_episode_count}`}))}/></Form.Item>
    {drama&&<Space wrap style={{marginBottom:12}}><Button type="primary" icon={<FolderOpenOutlined/>} loading={action==='connecting'||localStatus==='checking'} disabled={building&&action!=='connecting'} onClick={connectLocalSource}>{usingLocal?'更换本地文件夹':'选择本地文件夹'}</Button><Typography.Text type="secondary">只授权本机读取和编辑，不上传视频</Typography.Text></Space>}
    {usingLocal&&localSource&&<Alert type="success" showIcon message={`已连接本地文件夹：${localSource.folder_name}`} description={<Space direction="vertical" size={0}><Typography.Text ellipsis={{tooltip:localSource.absolute_path}}>{localSource.absolute_path}</Typography.Text><Typography.Text type="secondary">{localSource.file_count} 个视频 · {formatSize(localSource.total_bytes)} · 竖版封面 {localSource.covers.vertical?'已识别':'未识别'} · 方形封面 {localSource.covers.square?'已识别':'未识别'}</Typography.Text></Space>} style={{marginBottom:12}}/>}
    {drama&&<Space wrap className="meta-drama-tags"><Tag color={usingLocal?'green':'default'}>{usingLocal?'本地工作区':'服务器素材'}</Tag><Tag>源文件 {usingLocal?localSource?.file_count:drama.episode_count} 集</Tag><Tag color={source?.ready?'green':'default'}>可投递 {source?.episode_count??0} 集</Tag><Tag color={(usingLocal?localSource?.covers.vertical:drama.cover_vertical_path)?'green':'red'}>竖版封面</Tag><Tag color={(usingLocal?localSource?.covers.square:drama.cover_square_path)?'green':'red'}>方形封面</Tag>{Boolean(usingLocal?localSource?.covers.horizontal:drama.cover_horizontal_path)&&<Tag color="green">横版封面</Tag>}<Button type="link" size="small" icon={<EditOutlined/>} onClick={()=>navigate(`/dramas/${drama.id}`)}>编辑剧目</Button></Space>}
    {drama&&(source?.ready?<Alert type="success" showIcon message={usingLocal?`已从本机读取 ${source.episode_count} 个${source.source_mode==='factory_meta_split'?'内容工厂 Meta 单集':'视频文件'}`:`已读取内容工厂生成的 ${source.episode_count} 个 Meta 单集`} description={<Typography.Text ellipsis={{tooltip:source.files.join('、')}}>{source.files.join('、')}</Typography.Text>}/>:<Alert type="warning" showIcon message="尚无可投递视频" description={<Space><span>可直接选择本地素材文件夹，或</span><Button type="link" onClick={()=>navigate(`/factory?drama=${drama.id}`)}>前往内容工厂生成 Meta 逐集切分</Button></Space>}/>) }
  </Card>
  <Card title="2. Meta 必填信息">
    <Form.Item name="series_slug" label="英文文件夹名（可留空自动生成）"><Input placeholder="例如 boss-like-me"/></Form.Item>
    <Form.Item name="description" label="剧情简介（来自剧目任务）" rules={[{required:true,message:'Meta 要求填写系列简介'}]}><Input.TextArea rows={3} disabled={Boolean(drama?.description)}/></Form.Item>
    <div className="form-grid"><Form.Item name="locale" label="语种代码" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="release_date" label="首发日期 MM/DD/YYYY" rules={[{required:true}]}><Input/></Form.Item></div>
    <Form.Item name="genres" label="题材分类（来自剧目任务）" rules={[{required:true}]}><Select mode="multiple" disabled={Boolean(drama?.genres.length)} options={genres.map(x=>({value:x,label:x}))}/></Form.Item>
    <Space size="large" wrap><Form.Item name="ai_content" valuePropName="checked" label="AI 标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item><Form.Item name="dubbed_content" valuePropName="checked" label="配音标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item></Space>
    <Button block size="large" type="primary" loading={action==='build'||action==='selecting'||pendingForDrama} disabled={building||pendingForDrama||!drama||!source?.ready} icon={<FolderOpenOutlined/>} onClick={chooseAndBuild}>{pendingForDrama?'后台正在生成':directFolderSave||localRuntime||usingLocal?'选择本机位置并生成':'生成并下载 ZIP 到本机'}</Button>
    {action==='build'&&<div className="meta-build-status">{exportProgress?<><Typography.Text>{exportProgress.label}</Typography.Text><Progress percent={exportProgress.percent} status="active" showInfo={false}/></>:<Alert type="info" showIcon message="正在校验视频，任务登记后即使刷新页面也会继续生成"/>}</div>}
  </Card></div></Form>

  {check&&<Card title="校验结果" className="validation-card"><Alert type={check.ready?'success':'error'} showIcon message={check.ready?'文件符合投递要求':'需要处理后再生成'} description={check.blockers.length?<ul>{check.blockers.map(x=><li key={x}>{x}</li>)}</ul>:`共 ${check.episode_count} 集，文件名将统一为 ${check.series_slug}_epXXX_${String(check.episode_count).padStart(3,'0')}.mp4`}/>{check.automatic_fixes.length>0&&<List size="small" dataSource={check.automatic_fixes} renderItem={x=><List.Item><CheckCircleOutlined className="ok-icon"/> {x}</List.Item>}/>}</Card>}

  <Card title="3. 已生成文件夹" className="table-card">{packages.length?<Table rowKey="id" dataSource={packages} pagination={false} scroll={{x:760}} columns={[
    {title:'剧目',render:(_,row)=>dramas.find(x=>x.id===row.drama_id)?.title||row.series_slug},
    {title:'文件夹名',dataIndex:'series_slug'},
    {title:'状态',width:150,render:(_,row)=>activePackageStatuses.has(row.status)?<Tag color="processing">{row.status==='queued'?'等待生成':'正在生成'}</Tag>:row.status==='failed'?<Typography.Text type="danger" ellipsis={{tooltip:row.last_error}}>生成失败</Typography.Text>:row.status==='missing'?<Tag color="red">文件不在{usingLocal?'本机':'服务器'}</Tag>:<Tag color="green">{usingLocal?'本机':'服务器'}已生成</Tag>},
    {title:'生成时间',width:180,dataIndex:'created_at',render:(x:string)=>new Date(x).toLocaleString()},
    {title:'存档位置',dataIndex:'output_dir',render:(x:string)=><Typography.Text ellipsis={{tooltip:x}} copyable={Boolean(x)}>{x||'生成完成后显示'}</Typography.Text>},
    {title:'保存',width:220,render:(_,row)=>{const unavailable=unavailablePackageStatuses.has(row.status);return <Space><Button size="small" type="primary" icon={<FolderOpenOutlined/>} loading={action===`export-${row.id}`||action===`selecting-${row.id}`} disabled={unavailable||(building&&action!==`export-${row.id}`&&action!==`selecting-${row.id}`)} onClick={()=>saveExisting(row)}>{directFolderSave||localRuntime||usingLocal?'保存到本机':'下载 ZIP'}</Button>{(localRuntime||usingLocal)&&<Button size="small" disabled={unavailable||building} onClick={()=>openExisting(row)}>打开当前文件夹</Button>}</Space>}},
    {title:'下一步',width:150,render:()=> <Button type="primary" icon={<PlatformLogo platform="instagram" size={15}/>} href="https://www.instagram.com/sfs_tools" target="_blank">打开 SFS Tools</Button>},
  ]}/>:<Alert type="info" showIcon message="选择电脑上的保存位置后，系统会自动创建完整的 Meta 合规文件夹"/>}</Card>
 </div>
}
