import { Alert,Button,Card,Form,Input,List,Progress,Select,Space,Steps,Switch,Table,Tag,Typography,Upload,message } from 'antd'
import { CheckCircleOutlined,EditOutlined,FolderOpenOutlined,SafetyCertificateOutlined } from '@ant-design/icons'
import { useEffect,useMemo,useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api,type Drama,type MetaPackage,type MetaPreflight,type MetaSFSInput } from '../api'
import { PlatformLogo } from '../components/PlatformBrand'

const genres=['Action','Adventure','Animated','Comedy','Crime','Documentary','Drama','Family','Fantasy','Historical','Horror','Musical','Mystery','Noir','Reality','Romance','Science fiction','Sports','Thriller','Western']
const imageExtensions=new Set(['jpg','jpeg','png','webp'])
const allowedExtensions=new Set(['mp4','mov','mkv','webm','srt','vtt','jpg','jpeg','png','webp'])
const defaults={locale:'en_US',genres:['Drama'],release_date:new Date().toLocaleDateString('en-US',{month:'2-digit',day:'2-digit',year:'numeric'}),ai_content:false,dubbed_content:false}
type UploadPhase='waiting'|'uploading'|'done'|'error'
type UploadState={phase:UploadPhase;percent:number;message?:string}
type LocalWritable={write:(data:Uint8Array|Blob)=>Promise<void>;close:()=>Promise<void>;abort:()=>Promise<void>}
type LocalFileHandle={createWritable:()=>Promise<LocalWritable>}
type LocalDirectoryHandle={name:string;getDirectoryHandle:(name:string,options:{create:boolean})=>Promise<LocalDirectoryHandle>;getFileHandle:(name:string,options:{create:boolean})=>Promise<LocalFileHandle>}
type DirectoryPickerWindow=Window&{showDirectoryPicker?:(options:{mode:'readwrite'})=>Promise<LocalDirectoryHandle>}
type OutputDestination={kind:'browser';handle:LocalDirectoryHandle}|{kind:'server';token:string;name:string}|{kind:'download'}
const fileKey=(file:File)=>file.webkitRelativePath||`${file.name}-${file.size}-${file.lastModified}`
const fileLabel=(file:File)=>file.webkitRelativePath||file.name
const formatBytes=(bytes:number)=>bytes>=1024**3?`${(bytes/1024**3).toFixed(1)}GB`:`${(bytes/1024**2).toFixed(bytes>=100*1024**2?0:1)}MB`

export default function MetaDelivery({embedded=false}:{embedded?:boolean}){
 const[dramas,setDramas]=useState<Drama[]>([])
 const[check,setCheck]=useState<MetaPreflight>()
 const[packages,setPackages]=useState<MetaPackage[]>([])
 const[files,setFiles]=useState<File[]>([])
 const[uploadStates,setUploadStates]=useState<Record<string,UploadState>>({})
 const[action,setAction]=useState<string|null>(null)
 const[exportProgress,setExportProgress]=useState<{label:string;percent:number}|null>(null)
 const[msg,ctx]=message.useMessage()
 const navigate=useNavigate()
 const[form]=Form.useForm()
 const dramaId=Form.useWatch('drama_id',form)
 const drama=dramas.find(x=>x.id===dramaId)
 const videoCount=useMemo(()=>files.filter(file=>!imageExtensions.has(file.name.split('.').pop()?.toLowerCase()||'')&&!['srt','vtt'].includes(file.name.split('.').pop()?.toLowerCase()||'')).length,[files])
 const totalBytes=useMemo(()=>files.reduce((sum,file)=>sum+file.size,0),[files])
 const uploadedCount=files.filter(file=>uploadStates[fileKey(file)]?.phase==='done').length
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

 const load=async()=>{const[d,p]=await Promise.all([api.list(),api.metaPackages()]);setDramas(d);setPackages(p);if(!form.getFieldValue('drama_id')&&d[0])form.setFieldValue('drama_id',d[0].id)}
 useEffect(()=>{load().catch(e=>msg.error(e.message))},[])
 useEffect(()=>{if(!drama)return;form.setFieldsValue({description:drama.description,genres:drama.genres,ai_content:drama.is_ai_generated,dubbed_content:drama.is_dubbed_content,locale:drama.language||'en_US'})},[drama?.id])
 const body=(values:any):MetaSFSInput=>({drama_id:values.drama_id,series_slug:String(values.series_slug||'').trim(),description:values.description,locale:values.locale,genres:values.genres,release_date:values.release_date,cast_list:[],tags:[],geogating:[],ai_content:Boolean(values.ai_content),dubbed_content:Boolean(values.dubbed_content),include_episode_csv:false,include_thumbnails:false})
 const selectFiles=(next:File[])=>{
   setFiles(next);setCheck(undefined)
   setUploadStates(Object.fromEntries(next.map(file=>[fileKey(file),{phase:'waiting',percent:0} satisfies UploadState])))
 }
 const validateSelectedFiles=()=>{
   const invalid=files.filter(file=>!allowedExtensions.has(file.name.split('.').pop()?.toLowerCase()||''))
   if(invalid.length)throw new Error(`文件夹包含不支持的文件：${invalid.slice(0,3).map(x=>x.name).join('、')}`)
 }
 const uploadSelectedFiles=async(selected:Drama)=>{
   validateSelectedFiles()
   const completed=new Set(files.filter(file=>uploadStates[fileKey(file)]?.phase==='done').map(fileKey))
   const ordered=[...files].sort((a,b)=>imageExtensions.has(a.name.split('.').pop()?.toLowerCase()||'')?1:imageExtensions.has(b.name.split('.').pop()?.toLowerCase()||'')?-1:0)
   for(const file of ordered){
     const key=fileKey(file)
     if(completed.has(key))continue
     const ext=file.name.split('.').pop()?.toLowerCase()||''
     setUploadStates(old=>({...old,[key]:{phase:'uploading',percent:old[key]?.percent||0}}))
     try{
       await api.uploadVideo(selected.title,'Meta 官方投递本地文件夹',file,value=>setUploadStates(old=>({...old,[key]:{phase:'uploading',percent:value}})),imageExtensions.has(ext)?'stills':'episodes')
       setUploadStates(old=>({...old,[key]:{phase:'done',percent:100}}))
     }catch(error){
       const detail=(error as Error).message||'上传失败'
       setUploadStates(old=>({...old,[key]:{phase:'error',percent:old[key]?.percent||0,message:detail}}))
       throw new Error(`${fileLabel(file)}：${detail}`)
     }
   }
 }
 const uploadOnly=async()=>{try{
   const values=await form.validateFields(['drama_id'])
   const selected=dramas.find(x=>x.id===values.drama_id)
   if(!selected)throw new Error('请选择剧目任务')
   if(!files.length)throw new Error('请先选择本地文件夹')
   setAction('upload');await uploadSelectedFiles(selected);await load();msg.success(`${files.length} 个文件已上传到剧库`)
 }catch(e){msg.error((e as Error).message)}finally{setAction(null)}}
 const build=async(destination:OutputDestination)=>{try{
   const values=await form.validateFields()
   validateSelectedFiles();setAction('build');setCheck(undefined);setExportProgress(null)
   if(files.length){
     const selected=dramas.find(x=>x.id===values.drama_id)
     if(!selected)throw new Error('请选择剧目任务')
     await uploadSelectedFiles(selected)
   }
   const result=await api.metaPreflight(body(values));setCheck(result)
   if(!result.ready){msg.warning(`发现 ${result.blockers.length} 个必须处理的问题`);return}
   if(!values.series_slug)form.setFieldValue('series_slug',result.series_slug)
   const item=await api.buildMetaPackage({...body(values),series_slug:result.series_slug,local_destination_token:destination.kind==='server'?destination.token:''})
   const savedPath=destination.kind==='browser'?await savePackageToDirectory(item,destination.handle):destination.kind==='download'?downloadPackage(item):item.output_dir
   msg.success(`合规文件夹已保存到 ${savedPath}`);setFiles([]);setUploadStates({});await load()
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
  <Steps size="small" current={check?.ready?2:files.length||drama?.episode_count?1:0} className="meta-steps" items={[{title:'选择剧目与本地文件'},{title:'自动命名与校验'},{title:'生成上传文件夹'}]}/>
  <Form form={form} layout="vertical" initialValues={defaults}><div className="split-workbench meta-workbench"><Card title="1. 选择文件夹">
    <Form.Item name="drama_id" label="剧目任务" rules={[{required:true,message:'请选择剧目任务'}]}><Select showSearch optionFilterProp="label" options={dramas.map(x=>({value:x.id,label:`${x.title} · 全集 ${x.total_episode_count}`}))}/></Form.Item>
    {drama&&<Space wrap className="meta-drama-tags"><Tag>已入库 {drama.episode_count} 个原片</Tag><Tag>总集数 {drama.total_episode_count}</Tag><Tag color={drama.cover_vertical_path?'green':'red'}>竖版封面</Tag><Tag color={drama.cover_square_path?'green':'red'}>方形封面</Tag>{drama.cover_horizontal_path&&<Tag color="green">横版封面</Tag>}<Button type="link" size="small" icon={<EditOutlined/>} onClick={()=>navigate('/dramas')}>编辑剧目</Button></Space>}
    <Upload.Dragger directory multiple disabled={building} showUploadList={false} beforeUpload={()=>false} fileList={files.map((file,index)=>({uid:`${index}-${fileKey(file)}`,name:fileLabel(file),originFileObj:file as any}))} onChange={({fileList})=>selectFiles(fileList.map(x=>x.originFileObj).filter(Boolean) as File[])} accept=".mp4,.mov,.mkv,.webm,.srt,.vtt,.jpg,.jpeg,.png,.webp"><p className="ant-upload-drag-icon"><FolderOpenOutlined/></p><p className="ant-upload-text">选择包含多集视频的本地文件夹</p><p className="ant-upload-hint">视频、字幕和单集缩略图</p></Upload.Dragger>
    {files.length>0&&<div className="meta-file-summary"><div className="meta-file-summary-head"><b>{videoCount} 个视频 · {files.length-videoCount} 个配套文件 · {formatBytes(totalBytes)}</b><Space><Tag color={uploadedCount===files.length?'green':'default'}>{uploadedCount}/{files.length} 已上传</Tag><Button type="link" size="small" disabled={building} onClick={()=>selectFiles([])}>清空</Button></Space></div>{files.map(file=>{const state=uploadStates[fileKey(file)]||{phase:'waiting',percent:0};return <div className="upload-file" key={fileKey(file)}><div className="upload-file-name"><span title={fileLabel(file)}>{fileLabel(file)}</span>{state.phase==='waiting'&&<Tag>待上传</Tag>}{state.phase==='done'&&<Tag color="green">已入库</Tag>}{state.phase==='error'&&<Tag color="red">失败</Tag>}</div>{state.phase==='uploading'&&<Progress percent={state.percent}/>} {state.phase==='error'&&<Typography.Text type="danger">{state.message}</Typography.Text>}</div>})}<Button block type="primary" ghost loading={action==='upload'} disabled={building} onClick={uploadOnly}>上传选中的 {files.length} 个文件</Button></div>}
  </Card>
  <Card title="2. Meta 必填信息">
    <Form.Item name="series_slug" label="英文文件夹名（可留空自动生成）"><Input placeholder="例如 boss-like-me"/></Form.Item>
    <Form.Item name="description" label="剧情简介（来自剧目任务）" rules={[{required:true,message:'Meta 要求填写系列简介'}]}><Input.TextArea rows={3} disabled={Boolean(drama?.description)}/></Form.Item>
    <div className="form-grid"><Form.Item name="locale" label="语种代码" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="release_date" label="首发日期 MM/DD/YYYY" rules={[{required:true}]}><Input/></Form.Item></div>
    <Form.Item name="genres" label="题材分类（来自剧目任务）" rules={[{required:true}]}><Select mode="multiple" disabled={Boolean(drama?.genres.length)} options={genres.map(x=>({value:x,label:x}))}/></Form.Item>
    <Space size="large" wrap><Form.Item name="ai_content" valuePropName="checked" label="AI 标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item><Form.Item name="dubbed_content" valuePropName="checked" label="配音标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item></Space>
    <Button block size="large" type="primary" loading={action==='build'||action==='selecting'} disabled={building||!drama||(!files.length&&!drama.episode_count)} icon={<FolderOpenOutlined/>} onClick={chooseAndBuild}>{directFolderSave||localRuntime?'选择本机位置并生成':'生成并下载 ZIP 到本机'}</Button>
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
