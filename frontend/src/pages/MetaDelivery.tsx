import { Alert,Button,Card,Form,Input,List,Progress,Select,Space,Steps,Switch,Table,Tag,Typography,Upload,message } from 'antd'
import { CheckCircleOutlined,FolderOpenOutlined,SafetyCertificateOutlined,ThunderboltOutlined } from '@ant-design/icons'
import { useEffect,useMemo,useState } from 'react'
import { api,type Drama,type MetaPackage,type MetaPreflight,type MetaSFSInput } from '../api'

const genres=['Action','Adventure','Animated','Comedy','Crime','Documentary','Drama','Family','Fantasy','Historical','Horror','Musical','Mystery','Noir','Reality','Romance','Science fiction','Sports','Thriller','Western']
const imageExtensions=new Set(['jpg','jpeg','png','webp'])
const allowedExtensions=new Set(['mp4','mov','mkv','webm','srt','vtt','jpg','jpeg','png','webp'])
const defaults={locale:'en_US',genres:['Drama'],release_date:new Date().toLocaleDateString('en-US',{month:'2-digit',day:'2-digit',year:'numeric'}),ai_content:false,dubbed_content:false}

export default function MetaDelivery({embedded=false}:{embedded?:boolean}){
 const[dramas,setDramas]=useState<Drama[]>([])
 const[check,setCheck]=useState<MetaPreflight>()
 const[packages,setPackages]=useState<MetaPackage[]>([])
 const[files,setFiles]=useState<File[]>([])
 const[progress,setProgress]=useState<Record<string,number>>({})
 const[building,setBuilding]=useState(false)
 const[msg,ctx]=message.useMessage()
 const[form]=Form.useForm()
 const dramaId=Form.useWatch('drama_id',form)
 const drama=dramas.find(x=>x.id===dramaId)
 const videoCount=useMemo(()=>files.filter(file=>!imageExtensions.has(file.name.split('.').pop()?.toLowerCase()||'')&&!['srt','vtt'].includes(file.name.split('.').pop()?.toLowerCase()||'')).length,[files])

 const load=async()=>{const[d,p]=await Promise.all([api.list(),api.metaPackages()]);setDramas(d);setPackages(p);if(!form.getFieldValue('drama_id')&&d[0])form.setFieldValue('drama_id',d[0].id)}
 useEffect(()=>{load().catch(e=>msg.error(e.message))},[])
 const body=(values:any):MetaSFSInput=>({drama_id:values.drama_id,series_slug:String(values.series_slug||'').trim(),description:values.description,locale:values.locale,genres:values.genres,release_date:values.release_date,cast_list:[],tags:[],geogating:[],ai_content:Boolean(values.ai_content),dubbed_content:Boolean(values.dubbed_content),include_episode_csv:false,include_thumbnails:false})
 const build=async()=>{try{
   const values=await form.validateFields()
   const invalid=files.filter(file=>!allowedExtensions.has(file.name.split('.').pop()?.toLowerCase()||''))
   if(invalid.length)throw new Error(`文件夹包含不支持的文件：${invalid.slice(0,3).map(x=>x.name).join('、')}`)
   setBuilding(true);setCheck(undefined)
   if(files.length){
     const selected=dramas.find(x=>x.id===values.drama_id)
     if(!selected)throw new Error('请选择剧目任务')
     const ordered=[...files].sort((a,b)=>imageExtensions.has(a.name.split('.').pop()?.toLowerCase()||'')?1:imageExtensions.has(b.name.split('.').pop()?.toLowerCase()||'')?-1:0)
     for(const file of ordered){const ext=file.name.split('.').pop()?.toLowerCase()||'';await api.uploadVideo(selected.title,'Meta 官方投递本地文件夹',file,value=>setProgress(old=>({...old,[file.name]:value})),imageExtensions.has(ext)?'stills':'episodes')}
   }
   const result=await api.metaPreflight(body(values));setCheck(result)
   if(!result.ready){msg.warning(`发现 ${result.blockers.length} 个必须处理的问题`);return}
   if(!values.series_slug)form.setFieldValue('series_slug',result.series_slug)
   await api.buildMetaPackage({...body(values),series_slug:result.series_slug})
   msg.success('合规文件夹已生成，可手动上传到 Google Drive');setFiles([]);setProgress({});await load()
 }catch(e){msg.error((e as Error).message)}finally{setBuilding(false)}}

 return <div className={embedded?'meta-delivery':'workspace-page meta-delivery'}>{ctx}
  <div className="module-toolbar"><Space><b>Meta 官方投递</b><Tag icon={<SafetyCertificateOutlined/>} color="green">v260626</Tag><Tag>不调用 AI</Tag></Space></div>
  <Steps size="small" current={check?.ready?2:files.length||drama?.episode_count?1:0} className="meta-steps" items={[{title:'选择剧目与本地文件'},{title:'自动命名与校验'},{title:'生成上传文件夹'}]}/>
  <Form form={form} layout="vertical" initialValues={defaults}><div className="split-workbench meta-workbench"><Card title="1. 选择文件夹">
    <Form.Item name="drama_id" label="剧目任务" rules={[{required:true,message:'请选择剧目任务'}]}><Select showSearch optionFilterProp="label" options={dramas.map(x=>({value:x.id,label:`${x.title} · ${x.language} · 全集 ${x.total_episode_count}`}))}/></Form.Item>
    {drama&&<Space wrap className="meta-drama-tags"><Tag>已入库 {drama.episode_count} 个原片</Tag><Tag>全集 {drama.total_episode_count}</Tag></Space>}
    <Upload.Dragger directory multiple beforeUpload={()=>false} fileList={files.map((file,index)=>({uid:`${index}-${file.name}`,name:file.webkitRelativePath||file.name,status:'done',originFileObj:file as any}))} onChange={({fileList})=>setFiles(fileList.map(x=>x.originFileObj).filter(Boolean) as File[])} accept=".mp4,.mov,.mkv,.webm,.srt,.vtt,.jpg,.jpeg,.png,.webp"><p className="ant-upload-drag-icon"><FolderOpenOutlined/></p><p className="ant-upload-text">选择包含多集视频的本地文件夹</p><p className="ant-upload-hint">请同时放入一张封面图；系统会生成官方要求的竖版与方形封面</p></Upload.Dragger>
    {files.length>0&&<div className="meta-file-summary"><b>{videoCount} 个视频 · {files.length-videoCount} 个配套文件</b>{files.map(file=><div className="upload-file" key={file.webkitRelativePath||file.name}><span>{file.webkitRelativePath||file.name}</span><Progress percent={progress[file.name]??0}/></div>)}</div>}
  </Card>
  <Card title="2. Meta 必填信息">
    <Form.Item name="series_slug" label="英文文件夹名（可留空自动生成）"><Input placeholder="例如 boss-like-me"/></Form.Item>
    <Form.Item name="description" label="英文简介" rules={[{required:true,message:'Meta 要求填写系列简介'}]}><Input.TextArea rows={3}/></Form.Item>
    <div className="form-grid"><Form.Item name="locale" label="语种代码" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="release_date" label="首发日期 MM/DD/YYYY" rules={[{required:true}]}><Input/></Form.Item></div>
    <Form.Item name="genres" label="内容类型" rules={[{required:true}]}><Select mode="multiple" options={genres.map(x=>({value:x,label:x}))}/></Form.Item>
    <Space size="large" wrap><Form.Item name="ai_content" valuePropName="checked" label="素材含 AI 内容"><Switch/></Form.Item><Form.Item name="dubbed_content" valuePropName="checked" label="素材为配音内容"><Switch/></Form.Item></Space>
    <Button block size="large" type="primary" loading={building} disabled={!drama||(!files.length&&!drama.episode_count)} icon={<ThunderboltOutlined/>} onClick={build}>整理并生成合规文件夹</Button>
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
