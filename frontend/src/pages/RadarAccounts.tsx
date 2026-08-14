import { useCallback,useEffect,useMemo,useState } from 'react'
import { Button,Card,Form,Input,Modal,Popconfirm,Select,Space,Switch,Table,Tag,message } from 'antd'
import { DeleteOutlined,EditOutlined,ExportOutlined,PlusOutlined,ReloadOutlined } from '@ant-design/icons'
import { api,type MonitoredAccount } from '../api'
import { PlatformLogo,PlatformOption } from '../components/PlatformBrand'

type AccountFormValue = {
  platform:'youtube'|'facebook'|'instagram'|'tiktok'
  display_name:string
  platform_account_id:string
  profile_url:string
  relationship_type:'own_creator'|'own_official'
  notes:string
}

const accountTypes={own_creator:'达人',own_official:'官方引流'} as const
const platformOptions=['youtube','facebook','instagram','tiktok'].map(value=>({value,label:<PlatformOption platform={value}/>}))

export default function RadarAccounts(){
 const[items,setItems]=useState<MonitoredAccount[]>([])
 const[total,setTotal]=useState(0)
 const[query,setQuery]=useState('')
 const[platform,setPlatform]=useState('')
 const[relationship,setRelationship]=useState('')
 const[page,setPage]=useState(1)
 const[loading,setLoading]=useState(false)
 const[saving,setSaving]=useState(false)
 const[removing,setRemoving]=useState<number>()
 const[editing,setEditing]=useState<MonitoredAccount|null>(null)
 const[modalOpen,setModalOpen]=useState(false)
 const[form]=Form.useForm<AccountFormValue>()
 const[messageApi,context]=message.useMessage()

 const load=useCallback(async(nextPage=page)=>{
  setLoading(true)
  try{
   const params=new URLSearchParams({page:String(nextPage),page_size:'20'})
   if(platform)params.set('platform',platform)
   if(relationship)params.set('relationship_type',relationship)
   if(query.trim())params.set('query',query.trim())
   const value=await api.monitoredAccounts(`?${params}`)
   setItems(value.items);setTotal(value.total)
  }catch(error){messageApi.error((error as Error).message)}finally{setLoading(false)}
 },[page,platform,query,relationship,messageApi])
 useEffect(()=>{void load()},[page,platform,relationship]) // eslint-disable-line react-hooks/exhaustive-deps

 const openCreate=()=>{
  setEditing(null)
  form.resetFields()
  form.setFieldsValue({platform:'youtube',relationship_type:'own_creator',display_name:'',platform_account_id:'',profile_url:'',notes:''})
  setModalOpen(true)
 }
 const openEdit=(row:MonitoredAccount)=>{
  setEditing(row)
  form.setFieldsValue({platform:row.platform as AccountFormValue['platform'],display_name:row.display_name,platform_account_id:row.platform_account_id||'',profile_url:row.profile_url||'',relationship_type:(row.relationship_type==='own_official'?'own_official':'own_creator'),notes:row.notes||''})
  setModalOpen(true)
 }
 const save=async()=>{
  const values=await form.validateFields()
  if(!values.platform_account_id.trim()&&!values.profile_url.trim()){
   messageApi.warning('平台账号 ID 和账号主页至少填写一项')
   return
  }
  setSaving(true)
  try{
   if(editing)await api.updateMonitoredAccount(editing.id,values)
   else await api.createMonitoredAccount(values)
   messageApi.success(editing?'账号已更新':'账号已加入监测')
   setModalOpen(false);setEditing(null);form.resetFields();await load(1);setPage(1)
  }catch(error){messageApi.error((error as Error).message)}finally{setSaving(false)}
 }
 const setActive=async(row:MonitoredAccount,active:boolean)=>{
  try{await api.updateMonitoredAccount(row.id,{active});messageApi.success(active?'已开始监测':'已停止监测');await load()}
  catch(error){messageApi.error((error as Error).message)}
 }
 const remove=async(row:MonitoredAccount)=>{
  setRemoving(row.id)
  try{
   await api.disableMonitoredAccount(row.id)
   messageApi.success('账号已从监测列表移除')
   if(items.length===1&&page>1)setPage(page-1)
   else await load()
  }catch(error){messageApi.error((error as Error).message)}finally{setRemoving(undefined)}
 }

 const columns=useMemo(()=>[
  {title:'账号',render:(_:unknown,row:MonitoredAccount)=><div className="radar-account-identity"><span className="radar-account-logo"><PlatformLogo platform={row.platform} size={22}/></span><div className="radar-account-name"><b>{row.display_name}</b><span>{row.platform_account_id||row.profile_url}</span></div></div>},
  {title:'类型',dataIndex:'relationship_type',width:120,render:(value:string)=><Tag color={value==='own_official'?'cyan':'green'}>{accountTypes[value as keyof typeof accountTypes]||'达人'}</Tag>},
  {title:'账号主页',width:110,render:(_:unknown,row:MonitoredAccount)=>row.profile_url?<Button size="small" href={row.profile_url} target="_blank" icon={<ExportOutlined/>}>打开</Button>:<span className="cell-sub">未填写</span>},
  {title:'监测状态',width:110,render:(_:unknown,row:MonitoredAccount)=><Switch checked={row.active} checkedChildren="监测中" unCheckedChildren="已停止" onChange={value=>void setActive(row,value)}/>},
  {title:'操作',width:160,render:(_:unknown,row:MonitoredAccount)=><Space size={2}><Button type="text" icon={<EditOutlined/>} onClick={()=>openEdit(row)}>编辑</Button><Popconfirm title="移除这个监测账号？" description="移除后不再参与后续识别，历史记录仍会保留。" okText="移除" cancelText="取消" okButtonProps={{danger:true}} onConfirm={()=>void remove(row)}><Button type="text" danger loading={removing===row.id} icon={<DeleteOutlined/>}>移除</Button></Popconfirm></Space>},
 ],[removing]) // eslint-disable-line react-hooks/exhaustive-deps

 return <div className="radar-accounts">{context}
  <div className="radar-toolbar radar-account-toolbar">
   <Space wrap>
    <Input.Search allowClear placeholder="搜索账号名称、ID 或主页" value={query} onChange={event=>setQuery(event.target.value)} onSearch={()=>{setPage(1);void load(1)}}/>
    <Select value={platform} onChange={value=>{setPlatform(value);setPage(1)}} options={[{value:'',label:'全部平台'},...platformOptions]}/>
    <Select value={relationship} onChange={value=>{setRelationship(value);setPage(1)}} options={[{value:'',label:'全部类型'},{value:'own_creator',label:'达人'},{value:'own_official',label:'官方引流'}]}/>
   </Space>
   <Space><Button icon={<ReloadOutlined/>} onClick={()=>void load()}/><Button type="primary" icon={<PlusOutlined/>} onClick={openCreate}>添加账号</Button></Space>
  </div>
  <Card className="radar-account-list-card">
   <Table rowKey="id" loading={loading} dataSource={items} columns={columns} pagination={{current:page,pageSize:20,total,showSizeChanger:false,showTotal:value=>`共 ${value} 个账号`,onChange:setPage}}/>
  </Card>
  <Modal open={modalOpen} title={editing?'编辑监测账号':'添加监测账号'} okText="保存" cancelText="取消" confirmLoading={saving} onOk={()=>void save()} onCancel={()=>{setModalOpen(false);setEditing(null);form.resetFields()}} destroyOnHidden>
   <Form form={form} layout="vertical" className="radar-account-form">
    <div className="radar-account-form-grid">
     <Form.Item name="platform" label="平台" rules={[{required:true,message:'请选择平台'}]}><Select options={platformOptions}/></Form.Item>
     <Form.Item name="relationship_type" label="账号类型" rules={[{required:true,message:'请选择账号类型'}]}><Select options={[{value:'own_creator',label:'达人'},{value:'own_official',label:'官方引流'}]}/></Form.Item>
    </div>
    <Form.Item name="display_name" label="账号名称" rules={[{required:true,whitespace:true,message:'请输入账号名称'}]}><Input maxLength={200} placeholder="例如 MiniDrama Hub"/></Form.Item>
    <Form.Item name="platform_account_id" label="平台账号 ID"><Input maxLength={255} placeholder="例如 YouTube Channel ID"/></Form.Item>
    <Form.Item name="profile_url" label="账号主页"><Input maxLength={500} placeholder="https://..."/></Form.Item>
    <Form.Item name="notes" label="备注"><Input.TextArea rows={3} maxLength={1000}/></Form.Item>
   </Form>
  </Modal>
 </div>
}
