import { useEffect,useState } from 'react'
import { Avatar,Button,Card,DatePicker,Empty,Form,Input,message,Select,Space,Table,Tag,Typography } from 'antd'
import { CheckCircleOutlined, LinkOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons'
import dayjs,{type Dayjs} from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { api,type Account,type HotNote } from '../api'

export default function Operations(){
  const [accounts,setAccounts]=useState<Account[]>([])
  const [notes,setNotes]=useState<HotNote[]>([])
  const [checking,setChecking]=useState<number>()
  const [msg,holder]=message.useMessage()
  const navigate=useNavigate()
  const load=async()=>{const [a,n]=await Promise.all([api.accounts(),api.hotNotes()]);setAccounts(a);setNotes(n)}
  useEffect(()=>{load().catch(e=>msg.error(e.message))},[])
  const create=async(v:{content:string;platform:string;expires_at:Dayjs})=>{await api.createHotNote({content:v.content,platform:v.platform,expires_at:v.expires_at.toISOString()});msg.success('热点已记录');await load()}
  const expire=async(r:HotNote)=>{await api.updateHotNote(r.id,{content:r.content,platform:r.platform,expires_at:dayjs().subtract(1,'day').toISOString()});msg.success('已归档');await load()}
  const check=async(id:number)=>{setChecking(id);try{await api.checkAccount(id);msg.success('TikTok 连接有效');await load()}catch(e){msg.error(e instanceof Error?e.message:'检测失败')}finally{setChecking(undefined)}}
  const tiktok=accounts.filter(x=>x.platform==='tiktok')
  const cols=[
    {title:'热点',dataIndex:'content'},
    {title:'平台',dataIndex:'platform',render:(x:string)=><Tag>{x.toUpperCase()}</Tag>},
    {title:'有效期',dataIndex:'expires_at',render:(x:string)=><Tag color={dayjs(x).isBefore(dayjs(),'day')?'default':'green'}>{dayjs(x).format('YYYY-MM-DD')}</Tag>},
    {title:'操作',render:(_:unknown,r:HotNote)=><Space><Button onClick={()=>expire(r)}>归档</Button><Button danger onClick={()=>api.deleteHotNote(r.id).then(load)}>删除</Button></Space>},
  ]
  return <div className="workspace-page">{holder}
    <Space className="page-heading" align="start" wrap><Typography.Title level={2}>TikTok 运营台</Typography.Title><Button icon={<LinkOutlined/>} onClick={()=>navigate('/matrix')}>管理平台连接</Button></Space>
    <Card title="TikTok 账号连接" className="table-card">
      {tiktok.length?tiktok.map(a=><div key={a.id} className="connection-row">
        <Space><Avatar src={a.avatar_url}>{a.name.slice(0,1)}</Avatar><div><b>{a.name}</b><div className="cell-sub">{a.platform_user_id||'尚未读取平台身份'}</div></div></Space>
        <Space wrap>{a.status==='connected'?<Tag icon={<CheckCircleOutlined/>} color="success">已连接</Tag>:<Tag icon={<WarningOutlined/>} color="warning">未连接</Tag>}{a.capabilities.map(x=><Tag key={x}>{x}</Tag>)}<Button icon={<ReloadOutlined/>} loading={checking===a.id} onClick={()=>check(a.id)}>检测</Button></Space>
      </div>):<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有 TikTok 账号"><Button type="primary" onClick={()=>navigate('/matrix')}>添加并连接账号</Button></Empty>}
    </Card>
    <Card title="记录热点" className="form-card"><Form layout="inline" onFinish={create} initialValues={{platform:'tiktok',expires_at:dayjs().add(7,'day')}}><Form.Item name="content" label="内容 / 标签" rules={[{required:true,message:'请输入热点'}]}><Input placeholder="#暑期追剧"/></Form.Item><Form.Item name="platform" label="平台"><Select style={{width:140}} options={['tiktok','instagram','facebook','youtube','all'].map(x=>({value:x,label:x.toUpperCase()}))}/></Form.Item><Form.Item name="expires_at" label="失效日期" rules={[{required:true}]}><DatePicker/></Form.Item><Button type="primary" htmlType="submit">记录</Button></Form></Card>
    <Card title="热点素材库"><Table rowKey="id" dataSource={notes} columns={cols} locale={{emptyText:'尚未记录热点'}} scroll={{x:700}}/></Card>
  </div>
}
