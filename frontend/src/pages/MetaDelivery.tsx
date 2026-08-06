import { Alert,Button,Card,Form,Input,List,Progress,Select,Space,Steps,Switch,Table,Tag,Typography,Upload,message } from 'antd'
import { CheckCircleOutlined,FolderOpenOutlined,SafetyCertificateOutlined,ThunderboltOutlined } from '@ant-design/icons'
import { useEffect,useMemo,useState } from 'react'
import { api,type Drama,type MetaPackage,type MetaPreflight,type MetaSFSInput } from '../api'

const genres=['Action','Adventure','Animated','Comedy','Crime','Documentary','Drama','Family','Fantasy','Historical','Horror','Musical','Mystery','Noir','Reality','Romance','Science fiction','Sports','Thriller','Western']
const imageExtensions=new Set(['jpg','jpeg','png','webp'])
const allowedExtensions=new Set(['mp4','mov','mkv','webm','srt','vtt','jpg','jpeg','png','webp'])
const defaults={locale:'en_US',genres:['Drama'],release_date:new Date().toLocaleDateString('en-US',{month:'2-digit',day:'2-digit',year:'numeric'}),ai_content:false,dubbed_content:false}
type UploadPhase='waiting'|'uploading'|'done'|'error'
type UploadState={phase:UploadPhase;percent:number;message?:string}
const fileKey=(file:File)=>file.webkitRelativePath||`${file.name}-${file.size}-${file.lastModified}`
const fileLabel=(file:File)=>file.webkitRelativePath||file.name
const formatBytes=(bytes:number)=>bytes>=1024**3?`${(bytes/1024**3).toFixed(1)}GB`:`${(bytes/1024**2).toFixed(bytes>=100*1024**2?0:1)}MB`

export default function MetaDelivery({embedded=false}:{embedded?:boolean}){
 const[dramas,setDramas]=useState<Drama[]>([])
 const[check,setCheck]=useState<MetaPreflight>()
 const[packages,setPackages]=useState<MetaPackage[]>([])
 const[files,setFiles]=useState<File[]>([])
 const[uploadStates,setUploadStates]=useState<Record<string,UploadState>>({})
 const[action,setAction]=useState<'upload'|'build'|null>(null)
 const[msg,ctx]=message.useMessage()
 const[form]=Form.useForm()
 const dramaId=Form.useWatch('drama_id',form)
 const drama=dramas.find(x=>x.id===dramaId)
 const videoCount=useMemo(()=>files.filter(file=>!imageExtensions.has(file.name.split('.').pop()?.toLowerCase()||'')&&!['srt','vtt'].includes(file.name.split('.').pop()?.toLowerCase()||'')).length,[files])
 const totalBytes=useMemo(()=>files.reduce((sum,file)=>sum+file.size,0),[files])
 const uploadedCount=files.filter(file=>uploadStates[fileKey(file)]?.phase==='done').length
 const building=action!==null

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
 const build=async()=>{try{
   const values=await form.validateFields()
   validateSelectedFiles();setAction('build');setCheck(undefined)
   if(files.length){
     const selected=dramas.find(x=>x.id===values.drama_id)
     if(!selected)throw new Error('请选择剧目任务')
     await uploadSelectedFiles(selected)
   }
   const result=await api.metaPreflight(body(values));setCheck(result)
   if(!result.ready){msg.warning(`发现 ${result.blockers.length} 个必须处理的问题`);return}
   if(!values.series_slug)form.setFieldValue('series_slug',result.series_slug)
   await api.buildMetaPackage({...body(values),series_slug:result.series_slug})
   msg.success('合规文件夹已生成，可手动上传到 Google Drive');setFiles([]);setUploadStates({});await load()
 }catch(e){msg.error((e as Error).message)}finally{setAction(null)}}

 return <div className={embedded?'meta-delivery':'workspace-page meta-delivery'}>{ctx}
  {!embedded&&<div className="page-heading"><Typography.Title level={2}>Meta 官方投递</Typography.Title></div>}
  <div className="module-toolbar"><Space><b>Meta 官方投递</b><Tag icon={<SafetyCertificateOutlined/>} color="green">v260626</Tag><Tag>不调用 AI</Tag></Space></div>
  <Steps size="small" current={check?.ready?2:files.length||drama?.episode_count?1:0} className="meta-steps" items={[{title:'选择剧目与本地文件'},{title:'自动命名与校验'},{title:'生成上传文件夹'}]}/>
  <Form form={form} layout="vertical" initialValues={defaults}><div className="split-workbench meta-workbench"><Card title="1. 选择文件夹">
    <Form.Item name="drama_id" label="剧目任务" rules={[{required:true,message:'请选择剧目任务'}]}><Select showSearch optionFilterProp="label" options={dramas.map(x=>({value:x.id,label:`${x.title} · 全集 ${x.total_episode_count}`}))}/></Form.Item>
    {drama&&<Space wrap className="meta-drama-tags"><Tag>已入库 {drama.episode_count} 个原片</Tag><Tag>总集数 {drama.total_episode_count}</Tag>{drama.genres.map(genre=><Tag key={genre}>{genre}</Tag>)}{drama.is_ai_generated&&<Tag color="purple">AI 内容</Tag>}{drama.is_dubbed_content&&<Tag color="blue">配音内容</Tag>}</Space>}
    <Upload.Dragger directory multiple disabled={building} showUploadList={false} beforeUpload={()=>false} fileList={files.map((file,index)=>({uid:`${index}-${fileKey(file)}`,name:fileLabel(file),originFileObj:file as any}))} onChange={({fileList})=>selectFiles(fileList.map(x=>x.originFileObj).filter(Boolean) as File[])} accept=".mp4,.mov,.mkv,.webm,.srt,.vtt,.jpg,.jpeg,.png,.webp"><p className="ant-upload-drag-icon"><FolderOpenOutlined/></p><p className="ant-upload-text">选择包含多集视频的本地文件夹</p><p className="ant-upload-hint">请同时放入一张封面图；系统会生成官方要求的竖版与方形封面</p></Upload.Dragger>
    {files.length>0&&<div className="meta-file-summary"><div className="meta-file-summary-head"><b>{videoCount} 个视频 · {files.length-videoCount} 个配套文件 · {formatBytes(totalBytes)}</b><Space><Tag color={uploadedCount===files.length?'green':'default'}>{uploadedCount}/{files.length} 已上传</Tag><Button type="link" size="small" disabled={building} onClick={()=>selectFiles([])}>清空</Button></Space></div>{files.map(file=>{const state=uploadStates[fileKey(file)]||{phase:'waiting',percent:0};return <div className="upload-file" key={fileKey(file)}><div className="upload-file-name"><span title={fileLabel(file)}>{fileLabel(file)}</span>{state.phase==='waiting'&&<Tag>待上传</Tag>}{state.phase==='done'&&<Tag color="green">已入库</Tag>}{state.phase==='error'&&<Tag color="red">失败</Tag>}</div>{state.phase==='uploading'&&<Progress percent={state.percent}/>} {state.phase==='error'&&<Typography.Text type="danger">{state.message}</Typography.Text>}</div>})}<Button block type="primary" ghost loading={action==='upload'} disabled={building} onClick={uploadOnly}>上传选中的 {files.length} 个文件</Button></div>}
  </Card>
  <Card title="2. Meta 必填信息">
    <Form.Item name="series_slug" label="英文文件夹名（可留空自动生成）"><Input placeholder="例如 boss-like-me"/></Form.Item>
    <Form.Item name="description" label="剧情简介（来自剧目任务）" rules={[{required:true,message:'Meta 要求填写系列简介'}]}><Input.TextArea rows={3} disabled={Boolean(drama?.description)}/></Form.Item>
    <div className="form-grid"><Form.Item name="locale" label="语种代码" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="release_date" label="首发日期 MM/DD/YYYY" rules={[{required:true}]}><Input/></Form.Item></div>
    <Form.Item name="genres" label="题材分类（来自剧目任务）" rules={[{required:true}]}><Select mode="multiple" disabled={Boolean(drama?.genres.length)} options={genres.map(x=>({value:x,label:x}))}/></Form.Item>
    <Space size="large" wrap><Form.Item name="ai_content" valuePropName="checked" label="AI 标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item><Form.Item name="dubbed_content" valuePropName="checked" label="配音标识（来自剧目任务）"><Switch disabled={Boolean(drama)}/></Form.Item></Space>
    <Button block size="large" type="primary" loading={action==='build'} disabled={building||!drama||(!files.length&&!drama.episode_count)} icon={<ThunderboltOutlined/>} onClick={build}>{files.length&&uploadedCount<files.length?'上传并生成合规文件夹':'校验并生成合规文件夹'}</Button>
  </Card></div></Form>

  {check&&<Card title="校验结果" className="validation-card"><Alert type={check.ready?'success':'error'} showIcon message={check.ready?'文件符合投递要求':'需要处理后再生成'} description={check.blockers.length?<ul>{check.blockers.map(x=><li key={x}>{x}</li>)}</ul>:`共 ${check.episode_count} 集，文件名将统一为 ${check.series_slug}_epXXX_${String(check.episode_count).padStart(3,'0')}.mp4`}/>{check.automatic_fixes.length>0&&<List size="small" dataSource={check.automatic_fixes} renderItem={x=><List.Item><CheckCircleOutlined className="ok-icon"/> {x}</List.Item>}/>}</Card>}

  <Card title="3. 已生成文件夹" className="table-card">{packages.length?<Table rowKey="id" dataSource={packages} pagination={false} scroll={{x:760}} columns={[
    {title:'剧目',render:(_,row)=>dramas.find(x=>x.id===row.drama_id)?.title||row.series_slug},
    {title:'文件夹名',dataIndex:'series_slug'},
    {title:'状态',width:130,render:()=> <Tag color="green">本地校验通过</Tag>},
    {title:'生成时间',width:180,dataIndex:'created_at',render:(x:string)=>new Date(x).toLocaleString()},
    {title:'本地路径',dataIndex:'output_dir',render:(x:string)=><Typography.Text ellipsis={{tooltip:x}} copyable>{x}</Typography.Text>},
    {title:'下一步',width:150,render:()=> <Button type="primary" href="https://www.instagram.com/sfs_tools" target="_blank">打开 SFS Tools</Button>},
  ]}/>:<Alert type="info" showIcon message="生成后，将整个根文件夹手动上传到 Google Drive"/>}</Card>
 </div>
}
