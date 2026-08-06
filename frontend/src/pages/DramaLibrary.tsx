import { useEffect,useMemo,useState } from 'react'
import { Button,Card,Collapse,Empty,Form,Input,InputNumber,message,Modal,Progress,Segmented,Select,Space,Spin,Table,Tag,Typography } from 'antd'
import { ExperimentOutlined,FolderOpenOutlined,PlusOutlined,ReloadOutlined,RocketOutlined,VideoCameraOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api,Drama,ScanLog } from '../api'

const languages=[
  {value:'en_US',label:'英语 · en_US'},
  {value:'es_MX',label:'西班牙语 · es_MX'},
  {value:'pt_BR',label:'葡萄牙语 · pt_BR'},
  {value:'id_ID',label:'印尼语 · id_ID'},
  {value:'th_TH',label:'泰语 · th_TH'},
  {value:'vi_VN',label:'越南语 · vi_VN'},
  {value:'zh_CN',label:'中文 · zh_CN'},
]

export default function DramaLibrary(){
 const[items,setItems]=useState<Drama[]>([])
 const[loading,setLoading]=useState(true)
 const[logs,setLogs]=useState<ScanLog[]>([])
 const[view,setView]=useState<'tasks'|'generated'>('tasks')
 const[createOpen,setCreateOpen]=useState(false)
 const[registerOpen,setRegisterOpen]=useState(false)
 const[createForm]=Form.useForm()
 const[registerForm]=Form.useForm()
 const navigate=useNavigate()
 const[msg,context]=message.useMessage()

 const load=async()=>{try{setItems(await api.list())}catch(e){msg.error((e as Error).message)}finally{setLoading(false)}}
 useEffect(()=>{void load()},[])
 const scan=async()=>{setLoading(true);try{const result=await api.scan();setLogs(result.logs);await load();msg.success('本地素材已同步')}catch(e){msg.error((e as Error).message)}finally{setLoading(false)}}
 const createTask=async(values:{title:string;language:string;promotion_episode_count:number;total_episode_count:number})=>{try{const item=await api.createDramaTask(values);msg.success('剧目任务已建立');setCreateOpen(false);createForm.resetFields();await load();navigate(`/factory?drama=${item.id}`)}catch(e){msg.error((e as Error).message)}}
 const register=async(values:{title:string;absolute_path:string;source_note:string})=>{try{await api.registerDrama(values.title,values.absolute_path,values.source_note);msg.success('已有素材已登记');setRegisterOpen(false);registerForm.resetFields();await load()}catch(e){msg.error((e as Error).message)}}
 const generated=useMemo(()=>items.flatMap(drama=>drama.generated_files.map(file=>({key:`${drama.id}-${file.name}`,drama,file}))),[items])
 const logColor:Record<string,string>={imported:'green',updated:'blue',skipped:'orange',info:'default'}

 return <div className="workspace-page local-library">{context}
  <div className="page-heading page-heading-rich"><Typography.Title level={2}>剧库</Typography.Title><Space wrap><Button icon={<FolderOpenOutlined/>} onClick={()=>setRegisterOpen(true)}>登记已有素材</Button><Button icon={<ReloadOutlined/>} onClick={scan}>同步本地文件</Button><Button type="primary" icon={<PlusOutlined/>} onClick={()=>setCreateOpen(true)}>新建剧目任务</Button></Space></div>
  <Segmented block className="overview-pager library-pager" value={view} onChange={value=>setView(value as typeof view)} options={[{value:'tasks',label:`剧目任务 ${items.length}`},{value:'generated',label:`已生成 ${generated.length}`}]}/>
  {!!logs.length&&<Collapse className="scan-logs" items={[{key:'logs',label:`本次同步记录（${logs.length} 条）`,children:logs.map((entry,index)=><div className="scan-log-line" key={index}><Tag color={logColor[entry.status]}>{entry.status}</Tag><code>{entry.path}</code><span>{entry.message}</span></div>)}]}/>}
  <Spin spinning={loading}>{view==='tasks'?(items.length?<div className="card-grid local-drama-grid">{items.map(item=>{
    const progress=Math.min(100,Math.round((item.episode_count/Math.max(1,item.total_episode_count))*100))
    return <Card key={item.id} hoverable className="drama-task-card" actions={[<Button type="link" icon={<ExperimentOutlined/>} onClick={()=>navigate(`/factory?drama=${item.id}`)}>进入内容工厂</Button>,<Button type="link" onClick={()=>navigate(`/dramas/${item.id}`)}>查看资料</Button>]}>
      <Card.Meta avatar={<VideoCameraOutlined className="card-icon"/>} title={item.title} description={<Space direction="vertical" className="full-width" size={10}>
        <Space wrap><Tag>{item.language}</Tag><Tag color="blue">推广 {item.promotion_episode_count} 集</Tag><Tag>全集 {item.total_episode_count} 集</Tag>{item.generated_files.length>0&&<Tag color="green">成品 {item.generated_files.length}</Tag>}</Space>
        <div className="task-progress"><span>原片 {item.episode_count}/{item.total_episode_count}</span><Progress percent={progress} showInfo={false}/></div>
      </Space>}/>
    </Card>
  })}</div>:!loading&&<Card className="library-empty"><Empty description="还没有剧目任务"><Button type="primary" onClick={()=>setCreateOpen(true)}>新建第一个任务</Button></Empty></Card>):(
    <Card className="table-card">{generated.length?<Table rowKey="key" dataSource={generated} pagination={false} columns={[
      {title:'剧目',render:(_,row)=>row.drama.title},
      {title:'成品文件',render:(_,row)=><Typography.Text copyable>{row.file.name}</Typography.Text>},
      {title:'大小',width:120,render:(_,row)=>`${(row.file.size/1024/1024).toFixed(1)} MB`},
      {title:'生成时间',width:190,render:(_,row)=>new Date(row.file.created_at).toLocaleString()},
      {title:'操作',width:230,render:(_,row)=><Space><Button href={`/api/dramas/${row.drama.id}/generated/${encodeURIComponent(row.file.name)}`} target="_blank">查看</Button><Button type="primary" icon={<RocketOutlined/>} onClick={()=>navigate(`/publishing?drama=${row.drama.id}`)}>一键发布</Button></Space>},
    ]}/>:<Empty description="内容工厂终审通过的成品会出现在这里"/>}</Card>
  )}</Spin>

  <Modal title="新建剧目任务" open={createOpen} onCancel={()=>setCreateOpen(false)} footer={null} destroyOnHidden><Form form={createForm} layout="vertical" initialValues={{language:'en_US',promotion_episode_count:10,total_episode_count:80}} onFinish={createTask}>
    <Form.Item name="title" label="短剧名称" rules={[{required:true,message:'请输入短剧名称'}]}><Input autoFocus placeholder="例如：午夜契约"/></Form.Item>
    <Form.Item name="language" label="语种" rules={[{required:true}]}><Select showSearch options={languages}/></Form.Item>
    <div className="form-grid"><Form.Item name="promotion_episode_count" label="推广集数" dependencies={['total_episode_count']} rules={[{required:true},{validator:(_,value)=>value<=createForm.getFieldValue('total_episode_count')?Promise.resolve():Promise.reject(new Error('不能大于全集数'))}]}><InputNumber min={1} max={999} className="full-width"/></Form.Item><Form.Item name="total_episode_count" label="全集数" rules={[{required:true}]}><InputNumber min={1} max={999} className="full-width"/></Form.Item></div>
    <Button block size="large" type="primary" htmlType="submit">建立任务并进入内容工厂</Button>
  </Form></Modal>

  <Modal title="登记已有本地素材" open={registerOpen} onCancel={()=>setRegisterOpen(false)} footer={null} destroyOnHidden><Form form={registerForm} layout="vertical" onFinish={register}>
    <Form.Item name="title" label="剧名" rules={[{required:true}]}><Input/></Form.Item>
    <Form.Item name="absolute_path" label="本地文件夹路径" rules={[{required:true}]}><Input placeholder="例如 D:\短剧素材\我的短剧"/></Form.Item>
    <Form.Item name="source_note" label="素材来源" initialValue="已获授权素材" rules={[{required:true}]}><Input/></Form.Item>
    <Button block type="primary" htmlType="submit">校验并登记</Button>
  </Form></Modal>
 </div>
}
