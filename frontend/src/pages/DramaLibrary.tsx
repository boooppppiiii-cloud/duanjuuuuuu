import { useEffect,useMemo,useState } from 'react'
import { Button,Card,Collapse,Empty,Form,Input,InputNumber,message,Modal,Progress,Segmented,Select,Space,Spin,Switch,Tag,Typography } from 'antd'
import { CloudDownloadOutlined,FolderOpenOutlined,PictureOutlined,PlusOutlined,RadarChartOutlined,ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api,type CloudAsset,Drama,type PromotionDrama,ScanLog } from '../api'
import { theaterOptions } from '../options'

const genres=['Action','Adventure','Animated','Comedy','Crime','Documentary','Drama','Family','Fantasy','Historical','Horror','Musical','Mystery','Noir','Reality','Romance','Science fiction','Sports','Thriller','Western']
const languageOptions=[
 {value:'en_US',label:'英语 · en_US'},{value:'es_LA',label:'西班牙语 · es_LA'},{value:'pt_BR',label:'葡萄牙语 · pt_BR'},
 {value:'fr_FR',label:'法语 · fr_FR'},{value:'de_DE',label:'德语 · de_DE'},{value:'id_ID',label:'印尼语 · id_ID'},
 {value:'th_TH',label:'泰语 · th_TH'},{value:'vi_VN',label:'越南语 · vi_VN'},{value:'ja_JP',label:'日语 · ja_JP'},
 {value:'ko_KR',label:'韩语 · ko_KR'},{value:'zh_CN',label:'中文 · zh_CN'},
]
const languageLabel=(value:string)=>languageOptions.find(item=>item.value===value)?.label.split(' · ')[0]||value
const cardCoverKind=(item:Drama):'vertical'|'square'|'horizontal'|undefined=>item.cover_square_path?'square':item.cover_vertical_path?'vertical':item.cover_horizontal_path?'horizontal':undefined

export default function DramaLibrary(){
 const[items,setItems]=useState<Drama[]>([])
 const[cloud,setCloud]=useState<CloudAsset[]>([])
 const[promotionPool,setPromotionPool]=useState<PromotionDrama[]>([])
 const[loading,setLoading]=useState(true)
 const[logs,setLogs]=useState<ScanLog[]>([])
 const[view,setView]=useState<'tasks'|'cloud'>('tasks')
 const[query,setQuery]=useState('')
 const[language,setLanguage]=useState<string>()
 const[theater,setTheater]=useState<string>()
 const[poolFilter,setPoolFilter]=useState<'all'|'active'>('all')
 const[poolBusy,setPoolBusy]=useState<number>()
 const[createOpen,setCreateOpen]=useState(false)
 const[registerOpen,setRegisterOpen]=useState(false)
 const[createForm]=Form.useForm()
 const[registerForm]=Form.useForm()
 const navigate=useNavigate()
 const[msg,context]=message.useMessage()
 const localRuntime=['localhost','127.0.0.1','::1'].includes(window.location.hostname)

 const load=async()=>{try{const[dramas,assets,pool]=await Promise.all([api.list(),api.cloudAssets(),api.promotionPool()]);setItems(dramas);setCloud(assets);setPromotionPool(pool)}catch(e){msg.error((e as Error).message)}finally{setLoading(false)}}
 useEffect(()=>{void load()},[])
 const scan=async()=>{setLoading(true);try{const result=await api.scan();setLogs(result.logs);await load();msg.success('共享剧库已同步')}catch(e){msg.error((e as Error).message)}finally{setLoading(false)}}
 const createTask=async(values:{title:string;theater:string;description:string;total_episode_count:number;genres:string[];language:string;is_ai_generated:boolean;is_dubbed_content:boolean})=>{try{const item=await api.createDramaTask(values);msg.success('剧目任务已建立');setCreateOpen(false);createForm.resetFields();await load();navigate(`/factory?drama=${item.id}`)}catch(e){msg.error((e as Error).message)}}
 const register=async(values:{title:string;theater:string;absolute_path:string;source_note:string})=>{try{await api.registerDrama(values.title,values.theater,values.absolute_path,values.source_note);msg.success('已有素材已登记');setRegisterOpen(false);registerForm.resetFields();await load()}catch(e){msg.error((e as Error).message)}}
 const activePromotionIds=useMemo(()=>new Set(promotionPool.filter(item=>item.active).map(item=>item.drama_id)),[promotionPool])
 const filteredItems=useMemo(()=>{const keyword=query.trim().toLocaleLowerCase();return items.filter(item=>(!keyword||item.title.toLocaleLowerCase().includes(keyword))&&(!language||item.language===language)&&(!theater||item.theater===theater)&&(poolFilter==='all'||activePromotionIds.has(item.id)))},[items,query,language,theater,poolFilter,activePromotionIds])
 const togglePromotion=async(dramaId:number,active:boolean)=>{
  setPoolBusy(dramaId)
  try{
   if(active)await api.upsertPromotionDrama(dramaId,{source:'manual_confirmed'})
   else await api.removePromotionDrama(dramaId)
   setPromotionPool(await api.promotionPool())
   msg.success(active?'已加入推广剧目池':'已移出推广剧目池')
  }catch(e){msg.error((e as Error).message)}finally{setPoolBusy(undefined)}
 }
 const availableLanguages=useMemo(()=>Array.from(new Set(items.map(item=>item.language).filter(Boolean))).sort().map(value=>({value,label:`${languageLabel(value)} · ${value}`})),[items])
 const logColor:Record<string,string>={imported:'green',updated:'blue',skipped:'orange',info:'default'}

 return <div className="workspace-page local-library">{context}
  <div className="page-heading page-heading-rich"><Typography.Title level={2}>剧库</Typography.Title><Space wrap>{localRuntime&&<Button icon={<FolderOpenOutlined/>} onClick={()=>setRegisterOpen(true)}>登记已有素材</Button>}<Button icon={<ReloadOutlined/>} onClick={scan}>{localRuntime?'同步素材目录':'刷新共享剧库'}</Button><Button type="primary" icon={<PlusOutlined/>} onClick={()=>setCreateOpen(true)}>新建剧目任务</Button></Space></div>
  <Segmented block className="overview-pager library-pager" value={view} onChange={value=>setView(value as typeof view)} options={[{value:'tasks',label:`剧目任务 ${items.length}`},{value:'cloud',label:`云剧库 ${cloud.length}`}]}/>
  {!!logs.length&&<Collapse className="scan-logs" items={[{key:'logs',label:`本次同步记录（${logs.length} 条）`,children:logs.map((entry,index)=><div className="scan-log-line" key={index}><Tag color={logColor[entry.status]}>{entry.status}</Tag><code>{entry.path}</code><span>{entry.message}</span></div>)}]}/>}
  {view==='tasks'&&<div className="library-filter-bar"><Input.Search allowClear value={query} onChange={event=>setQuery(event.target.value)} placeholder="搜索剧目名称"/><Select allowClear value={theater} onChange={setTheater} placeholder="全部剧场" options={theaterOptions}/><Select allowClear value={language} onChange={setLanguage} placeholder="全部语种" options={availableLanguages}/><Select value={poolFilter} onChange={setPoolFilter} options={[{value:'all',label:'全部剧目'},{value:'active',label:'推广剧目池'}]}/><span>{filteredItems.length} 部剧目</span></div>}
  <Spin spinning={loading}>{view==='tasks'?(items.length?(filteredItems.length?<div className="local-drama-grid">{filteredItems.map(item=>{
    const progress=Math.min(100,Math.round((item.episode_count/Math.max(1,item.total_episode_count))*100))
    const kind=cardCoverKind(item)
    return <Card key={item.id} hoverable className="drama-task-card" role="link" tabIndex={0} aria-label={`打开 ${item.title} 的剧目资料`} onClick={()=>navigate(`/dramas/${item.id}`)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();navigate(`/dramas/${item.id}`)}}} cover={<div className="drama-card-cover">{kind?<img src={`/api/dramas/${item.id}/covers/${kind}`} alt=""/>:<PictureOutlined/>}<span>{item.episode_count}/{item.total_episode_count} 集</span></div>}>
      <div className="drama-card-info"><Typography.Text strong ellipsis={{tooltip:item.title}}>{item.title}</Typography.Text><div className="drama-card-meta">{item.theater&&<Tag color="green">#{item.theater.replace(/^#+/,'').replace(/\s+/g,'')}</Tag>}<Tag>{languageLabel(item.language)}</Tag>{item.genres[0]&&<Tag>{item.genres[0]}</Tag>}</div><div className="drama-card-monitoring"><Tag color={activePromotionIds.has(item.id)?'green':'default'} icon={<RadarChartOutlined/>}>{activePromotionIds.has(item.id)?'推广监测中':'未加入推广池'}</Tag><Button size="small" type="text" loading={poolBusy===item.id} onClick={event=>{event.stopPropagation();void togglePromotion(item.id,!activePromotionIds.has(item.id))}} onKeyDown={event=>event.stopPropagation()}>{activePromotionIds.has(item.id)?'移出':'加入'}</Button></div><div className="drama-card-progress"><Progress percent={progress} showInfo={false} size="small"/><span>{progress}%</span></div></div>
    </Card>
  })}</div>:<Card className="library-empty"><Empty description="没有符合条件的剧目"><Button onClick={()=>{setQuery('');setLanguage(undefined);setTheater(undefined)}}>清除筛选</Button></Empty></Card>):!loading&&<Card className="library-empty"><Empty description="还没有剧目任务"><Button type="primary" onClick={()=>setCreateOpen(true)}>新建第一个任务</Button></Empty></Card>):(
    cloud.length?<div className="cloud-library-grid">{cloud.map(asset=>{const drama=items.find(item=>item.id===asset.drama_id);const kind=drama&&cardCoverKind(drama);return <Card key={asset.id} className="cloud-asset-card" cover={<div className="cloud-asset-cover">{kind?<img src={`/api/dramas/${asset.drama_id}/covers/${kind}`} alt=""/>:<PictureOutlined/>}<Tag>{asset.kind==='hook_full'?'高能片头版':asset.kind==='clean_full'?'净化完整版':'Meta 单集'}</Tag></div>}>
      <Typography.Text strong ellipsis={{tooltip:asset.filename}}>{asset.drama_title}</Typography.Text><Typography.Text type="secondary" ellipsis={{tooltip:asset.filename}}>{asset.filename}</Typography.Text><div className="cloud-asset-meta"><span>{(asset.size_bytes/1024/1024).toFixed(1)} MB</span><span>下载 {asset.download_count}</span></div><Button block icon={<CloudDownloadOutlined/>} href={`/api/factory/cloud-assets/${asset.id}/download`} target="_blank">下载</Button>
    </Card>})}</div>:<Card className="library-empty"><Empty description="还没有人把成品上传到云剧库"/></Card>
  )}</Spin>

  <Modal title="新建剧目任务" open={createOpen} onCancel={()=>setCreateOpen(false)} footer={null} width={620} destroyOnHidden><Form form={createForm} layout="vertical" initialValues={{genres:['Drama'],language:'en_US',total_episode_count:80,is_ai_generated:false,is_dubbed_content:false}} onFinish={createTask}>
    <Form.Item name="title" label="短剧名称" rules={[{required:true,message:'请输入短剧名称'}]}><Input autoFocus placeholder="例如：午夜契约"/></Form.Item>
    <Form.Item name="theater" label="剧场" extra="AI 撰写标题文案时会自动加入对应剧场标签。" rules={[{required:true,message:'请选择剧场'}]}><Select placeholder="选择剧场" options={theaterOptions}/></Form.Item>
    <Form.Item name="description" label="剧情简介" rules={[{required:true,message:'请输入剧情简介'}]}><Input.TextArea rows={4} placeholder="用于生成 Meta 系列 CSV，请填写完整剧情梗概"/></Form.Item>
    <div className="form-grid"><Form.Item name="total_episode_count" label="总集数" rules={[{required:true}]}><InputNumber min={1} max={999} className="full-width"/></Form.Item><Form.Item name="language" label="语种" rules={[{required:true}]}><Select showSearch optionFilterProp="label" options={languageOptions}/></Form.Item></div>
    <Form.Item name="genres" label="题材分类" rules={[{required:true,message:'至少选择一种题材'}]}><Select mode="multiple" options={genres.map(value=>({value,label:value}))}/></Form.Item>
    <div className="form-grid"><Form.Item name="is_ai_generated" label="AI 标识" valuePropName="checked"><Switch checkedChildren="包含 AI" unCheckedChildren="非 AI"/></Form.Item><Form.Item name="is_dubbed_content" label="配音标识" valuePropName="checked"><Switch checkedChildren="配音内容" unCheckedChildren="原声内容"/></Form.Item></div>
    <Button block size="large" type="primary" htmlType="submit">建立任务并进入内容工厂</Button>
  </Form></Modal>

  {localRuntime&&<Modal title="登记已有本地素材" open={registerOpen} onCancel={()=>setRegisterOpen(false)} footer={null} destroyOnHidden><Form form={registerForm} layout="vertical" onFinish={register}>
    <Form.Item name="title" label="剧名" rules={[{required:true}]}><Input/></Form.Item>
    <Form.Item name="theater" label="剧场" rules={[{required:true,message:'请选择剧场'}]}><Select placeholder="选择剧场" options={theaterOptions}/></Form.Item>
    <Form.Item name="absolute_path" label="本地文件夹路径" rules={[{required:true}]}><Input placeholder="例如 D:\短剧素材\我的短剧"/></Form.Item>
    <Form.Item name="source_note" label="素材来源" initialValue="已获授权素材" rules={[{required:true}]}><Input/></Form.Item>
    <Button block type="primary" htmlType="submit">校验并登记</Button>
  </Form></Modal>}
 </div>
}
