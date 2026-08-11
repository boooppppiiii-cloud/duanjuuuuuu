import { Alert,Button,Card,Form,Input,List,Progress,Select,Space,Steps,Switch,Table,Tag,Typography,message } from 'antd'
import { CheckCircleOutlined,EditOutlined,FolderOpenOutlined,SafetyCertificateOutlined } from '@ant-design/icons'
import { useEffect,useState } from 'react'
import { useNavigate,useSearchParams } from 'react-router-dom'
import { api,type Drama,type MetaFactorySource,type MetaPackage,type MetaPreflight,type MetaSFSInput } from '../api'
import { PlatformLogo } from '../components/PlatformBrand'

const genres=['Action','Adventure','Animated','Comedy','Crime','Documentary','Drama','Family','Fantasy','Historical','Horror','Musical','Mystery','Noir','Reality','Romance','Science fiction','Sports','Thriller','Western']
const defaults={locale:'en_US',genres:['Drama'],release_date:new Date().toLocaleDateString('en-US',{month:'2-digit',day:'2-digit',year:'numeric'}),ai_content:false,dubbed_content:false}
type LocalWritable={write:(data:Uint8Array|Blob)=>Promise<void>;close:()=>Promise<void>;abort:()=>Promise<void>}
type LocalFileHandle={createWritable:()=>Promise<LocalWritable>}
type LocalDirectoryHandle={name:string;getDirectoryHandle:(name:string,options:{create:boolean})=>Promise<LocalDirectoryHandle>;getFileHandle:(name:string,options:{create:boolean})=>Promise<LocalFileHandle>}
type DirectoryPickerWindow=Window&{showDirectoryPicker?:(options:{mode:'readwrite'})=>Promise<LocalDirectoryHandle>}
type OutputDestination={kind:'browser';handle:LocalDirectoryHandle}|{kind:'server';token:string;name:string}|{kind:'download'}

export default function MetaDelivery({embedded=false}:{embedded?:boolean}){
 const[dramas,setDramas]=useState<Drama[]>([])
 const[check,setCheck]=useState<MetaPreflight>()
 const[source,setSource]=useState<MetaFactorySource>()
 const[packages,setPackages]=useState<MetaPackage[]>([])
 const[action,setAction]=useState<string|null>(null)
 const[exportProgress,setExportProgress]=useState<{label:string;percent:number}|null>(null)
 const[msg,ctx]=message.useMessage()
 const navigate=useNavigate()
 const[params]=useSearchParams()
 const[form]=Form.useForm()
 const dramaId=Form.useWatch('drama_id',form)
 const drama=dramas.find(x=>x.id===dramaId)
 const building=action!==null
 const localRuntime=['localhost','127.0.0.1','::1'].includes(window.location.hostname)
 const directFolderSave=window.isSecureContext&&Boolean((window as DirectoryPickerWindow).showDirectoryPicker)

 const chooseOutputDirectory=async()=>{
   const picker=(window as DirectoryPickerWindow).showDirectoryPicker
   if(window.isSecureContext&&picker)return {kind:'browser',handle:await picker.call(window,{mode:'readwrite'})} satisfies OutputDestination
   if(localRuntime){const selected=await api.selectMetaOutputDirectory();return {kind:'server',...selected} satisfies OutputDestination}
   return {kind:'download'} satisfies OutputDestination
 }
 const downloadPackage=(item:MetaPackage)=>{
   const link=document.createElement('a')
   link.href=api.metaPackageArchiveUrl(item.id)
   link.download=`${item.series_slug}.zip`
   document.body.appendChild(link);link.click();link.remove()
   return '本机下载目录'
 }
 const savePackageToDirectory=async(item:MetaPackage,destination:LocalDirectoryHandle)=>{
   const manifest=await api.metaPackageFiles(item.id)
   const root=await destination.getDirectoryHandle(manifest.folder_name,{create:true})
   let written=0,lastPercent=-1
   for(const entry of manifest.files){
     const parts=entry.path.split('/').filter(Boolean)
     const filename=parts.pop()
     if(!filename)continue
     let folder=root
     for(const part of parts)folder=await folder.getDirectoryHandle(part,{create:true})
     const response=await fetch(api.metaPackageFileUrl(item.id,entry.path))
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

 const load=async()=>{const[d,p]=await Promise.all([api.list(),api.metaPackages()]);setDramas(d);setPackages(p);const requested=Number(params.get('drama'));if(!form.getFieldValue('drama_id'))form.setFieldValue('drama_id',d.some(item=>item.id===requested)?requested:d[0]?.id)}
 useEffect(()=>{load().catch(e=>msg.error(e.message))},[])
 useEffect(()=>{if(!drama)return;form.setFieldsValue({description:drama.description,genres:drama.genres,ai_content:drama.is_ai_generated,dubbed_content:drama.is_dubbed_content,locale:drama.language||'en_US'})},[drama?.id])
 useEffect(()=>{
   setCheck(undefined);setSource(undefined)
   if(!dramaId)return
   api.metaFactorySource(dramaId).then(setSource).catch(error=>msg.error(error.message))
 },[dramaId])
 const body=(values:any):MetaSFSInput=>({drama_id:values.drama_id,series_slug:String(values.series_slug||'').trim(),description:values.description,locale:values.locale,genres:values.genres,release_date:values.release_date,cast_list:[],tags:[],geogating:[],ai_content:Boolean(values.ai_content),dubbed_content:Boolean(values.dubbed_content),include_episode_csv:false,include_thumbnails:false})
 const build=async(destination:OutputDestination)=>{try{
   const values=await form.validateFields()
   if(!source?.ready)throw new Error('请先在内容工厂生成 Meta 逐集切分成品')
   setAction('build');setCheck(undefined);setExportProgress(null)
   const result=await api.metaPreflight(body(values));setCheck(result)
   if(!result.ready){msg.warning(`发现 ${result.blockers.length} 个必须处理的问题`);return}
   if(!values.series_slug)form.setFieldValue('series_slug',result.series_slug)
   const item=await api.buildMetaPackage({...body(values),series_slug:result.series_slug,local_destination_token:destination.kind==='server'?destination.token:''})
   const savedPath=destination.kind==='browser'?await savePackageToDirectory(item,destination.handle):destination.kind==='download'?downloadPackage(item):item.output_dir
   msg.success(`合规文件夹已保存到 ${savedPath}`);await load()
 }catch(e){if(!cancelled(e))msg.error((e as Error).message)}finally{setAction(null);setExportProgress(null)}}
 const chooseAndBuild=async()=>{try{setAction('selecting');const destination=await chooseOutputDirectory();setAction(null);await build(destination)}catch(e){if(!cancelled(e))msg.error((e as Error).message);setAction(null)}}
 const saveExisting=async(item:MetaPackage)=>{try{
   setAction(`selecting-${item.id}`);const destination=await chooseOutputDirectory();setAction(`export-${item.id}`);setExportProgress(null)
   const savedPath=destination.kind==='browser'?await savePackageToDirectory(item,destination.handle):destination.kind==='download'?downloadPackage(item):(await api.copyMetaPackageLocal(item.id,destination.token)).path
   msg.success(`已保存到 ${savedPath}`)
 }catch(e){if(!cancelled(e))msg.error((e as Error).message)}finally{setAction(null);setExportProgress(null)}}
 const openExisting=async(item:MetaPackage)=>{try{const result=await api.openMetaPackageFolder(item.id);msg.success(`已打开 ${result.path}`)}catch(e){msg.error((e as Error).message)}}

 return <div className={embedded?'meta-delivery':'workspace-page meta-delivery'}>{ctx}
  {!embedded&&<div className="page-heading"><Typography.Title level={2}><Space><PlatformLogo platform="meta" size={27}/><span>官方投递</span></Space></Typography.Title></div>}
  <div className="module-toolbar"><Space><PlatformLogo platform="meta" size={22}/><b>官方投递</b><Tag icon={<SafetyCertificateOutlined/>} color="green">v260626</Tag><Tag>{directFolderSave||localRuntime?'保存到本机文件夹':'保存为本机 ZIP'}</Tag></Space></div>
  <Steps size="small" current={check?.ready?2:source?.ready?1:0} className="meta-steps" items={[{title:'选择内容工厂成品'},{title:'自动命名与校验'},{title:'生成上传文件夹'}]}/>
  <Form form={form} layout="vertical" initialValues={defaults}><div className="split-workbench meta-workbench"><Card title="1. 选择内容工厂成品">
    <Form.Item name="drama_id" label="剧目任务" rules={[{required:true,message:'请选择剧目任务'}]}><Select showSearch optionFilterProp="label" options={dramas.map(x=>({value:x.id,label:`${x.title} · 全集 ${x.total_episode_count}`}))}/></Form.Item>
    {drama&&<Space wrap className="meta-drama-tags"><Tag>源文件 {drama.episode_count} 集</Tag><Tag color={source?.ready?'green':'default'}>投递成品 {source?.episode_count??0} 集</Tag><Tag color={drama.cover_vertical_path?'green':'red'}>竖版封面</Tag><Tag color={drama.cover_square_path?'green':'red'}>方形封面</Tag>{drama.cover_horizontal_path&&<Tag color="green">横版封面</Tag>}<Button type="link" size="small" icon={<EditOutlined/>} onClick={()=>navigate(`/dramas/${drama.id}`)}>编辑剧目</Button></Space>}
    {drama&&(source?.ready?<Alert type="success" showIcon message={`已读取内容工厂生成的 ${source.episode_count} 个 Meta 单集`} description={<Typography.Text ellipsis={{tooltip:source.files.join('、')}}>{source.files.join('、')}</Typography.Text>}/>:<Alert type="warning" showIcon message="尚未生成 Meta 投递成品" description={<Button type="link" onClick={()=>navigate(`/factory?drama=${drama.id}`)}>前往内容工厂生成 Meta 逐集切分</Button>}/>) }
  </Card>
  <Card title="2. Meta 必填信息">
    <Form.Item name="series_slug" label="英文文件夹名（可留空自动生成）"><Input placeholder="例如 boss-like-me"/></Form.Item>
    <Form.Item name="description" label="剧情简介（来自剧目任务）" rules={[{required:true,message:'Meta 要求填写系列简介'}]}><Input.TextArea rows={3} disabled={Boolean(drama?.description)}/></Form.Item>
    <div className="form-grid"><Form.Item name="locale" label="语种代码" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="release_date" label="首发日期 MM/DD/YYYY" rules={[{required:true}]}><Input/></Form.Item></div>
    <Form.Item name="genres" label="题材分类（来自剧目任务）" rules={[{required:true}]}><Select mode="multiple" disabled={Boolean(drama?.genres.length)} options={genres.map(x=>({value:x,label:x}))}/></Form.Item>
    <Space size="large" wrap><Form.Item name="ai_content" valuePropName="checked" label="AI 标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item><Form.Item name="dubbed_content" valuePropName="checked" label="配音标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item></Space>
    <Button block size="large" type="primary" loading={action==='build'||action==='selecting'} disabled={building||!drama||!source?.ready} icon={<FolderOpenOutlined/>} onClick={chooseAndBuild}>{directFolderSave||localRuntime?'选择本机位置并生成':'生成并下载 ZIP 到本机'}</Button>
    {action==='build'&&<div className="meta-build-status">{exportProgress?<><Typography.Text>{exportProgress.label}</Typography.Text><Progress percent={exportProgress.percent}/></>:<Alert type="info" showIcon message="正在校验并转换视频，完成后会自动写入你选择的文件夹"/>}</div>}
  </Card></div></Form>

  {check&&<Card title="校验结果" className="validation-card"><Alert type={check.ready?'success':'error'} showIcon message={check.ready?'文件符合投递要求':'需要处理后再生成'} description={check.blockers.length?<ul>{check.blockers.map(x=><li key={x}>{x}</li>)}</ul>:`共 ${check.episode_count} 集，文件名将统一为 ${check.series_slug}_epXXX_${String(check.episode_count).padStart(3,'0')}.mp4`}/>{check.automatic_fixes.length>0&&<List size="small" dataSource={check.automatic_fixes} renderItem={x=><List.Item><CheckCircleOutlined className="ok-icon"/> {x}</List.Item>}/>}</Card>}

  <Card title="3. 已生成文件夹" className="table-card">{packages.length?<Table rowKey="id" dataSource={packages} pagination={false} scroll={{x:760}} columns={[
    {title:'剧目',render:(_,row)=>dramas.find(x=>x.id===row.drama_id)?.title||row.series_slug},
    {title:'文件夹名',dataIndex:'series_slug'},
    {title:'状态',width:140,render:(_,row)=>row.status==='missing'?<Tag color="red">文件不在服务器</Tag>:<Tag color="green">服务器已生成</Tag>},
    {title:'生成时间',width:180,dataIndex:'created_at',render:(x:string)=>new Date(x).toLocaleString()},
    {title:'服务器存档',dataIndex:'output_dir',render:(x:string)=><Typography.Text ellipsis={{tooltip:x}} copyable>{x}</Typography.Text>},
    {title:'保存',width:220,render:(_,row)=><Space><Button size="small" type="primary" icon={<FolderOpenOutlined/>} loading={action===`export-${row.id}`||action===`selecting-${row.id}`} disabled={row.status==='missing'||(building&&action!==`export-${row.id}`&&action!==`selecting-${row.id}`)} onClick={()=>saveExisting(row)}>{directFolderSave||localRuntime?'保存到本机':'下载 ZIP'}</Button>{localRuntime&&<Button size="small" disabled={row.status==='missing'||building} onClick={()=>openExisting(row)}>打开当前文件夹</Button>}</Space>},
    {title:'下一步',width:150,render:()=> <Button type="primary" icon={<PlatformLogo platform="instagram" size={15}/>} href="https://www.instagram.com/sfs_tools" target="_blank">打开 SFS Tools</Button>},
  ]}/>:<Alert type="info" showIcon message="选择电脑上的保存位置后，系统会自动创建完整的 Meta 合规文件夹"/>}</Card>
 </div>
}
