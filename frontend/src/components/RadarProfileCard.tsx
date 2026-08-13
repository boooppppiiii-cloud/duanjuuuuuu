import { useEffect,useState } from 'react'
import { Alert,Button,Card,Checkbox,Form,Input,Select,Space,Switch,Tag,message } from 'antd'
import { RadarChartOutlined,SaveOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api,type RadarProfile } from '../api'

export default function RadarProfileCard({dramaId}:{dramaId:number}){
 const[form]=Form.useForm();const[profile,setProfile]=useState<RadarProfile>();const[enabledQueryIds,setEnabledQueryIds]=useState<number[]>([]);const[saving,setSaving]=useState(false);const navigate=useNavigate();const[messageApi,context]=message.useMessage()
 useEffect(()=>{api.radarProfile(dramaId).then(value=>{setProfile(value);setEnabledQueryIds(value.queries.filter(item=>item.enabled).map(item=>item.id));form.setFieldsValue(value)}).catch(error=>void messageApi.error((error as Error).message))},[dramaId,form,messageApi])
 const save=async(values:Record<string,unknown>)=>{setSaving(true);try{const next=await api.saveRadarProfile(dramaId,{...values,queries:profile?.queries.map(item=>({id:item.id,enabled:enabledQueryIds.includes(item.id)}))||[]});setProfile(next);setEnabledQueryIds(next.queries.filter(item=>item.enabled).map(item=>item.id));form.setFieldsValue(next);messageApi.success('传播监测配置已保存')}catch(error){messageApi.error((error as Error).message)}finally{setSaving(false)}}
 return <Card title={<Space><RadarChartOutlined/>传播监测</Space>} extra={<Button onClick={()=>navigate(`/radar/dramas/${dramaId}`)}>进入搜索现场</Button>}>{context}
  <Form form={form} layout="vertical" onFinish={save} className="radar-profile-form" initialValues={{enabled:false,regions:['US'],languages:['en'],priority:'normal'}}>
   <Alert className="radar-pool-note" type="info" showIcon message="推广剧目池" description="开启后加入轻量推广剧目池，每天扫描一次；不会扫描整个剧库。账号真实发布和外部市场发现也会自动补充来源。"/>
   <div className="radar-profile-head"><Form.Item name="enabled" label="加入推广剧目池" valuePropName="checked"><Switch/></Form.Item><Form.Item name="priority" label="池内优先级"><Select options={[{value:'normal',label:'普通'},{value:'low',label:'低优先'},{value:'paused',label:'暂停'}]}/></Form.Item></div>
   <Form.Item name="official_title" label="官方英文名" rules={[{required:true,message:'请输入官方英文名'}]}><Input/></Form.Item>
   <div className="radar-profile-grid"><Form.Item name="aliases" label="剧名别名"><Select mode="tags" tokenSeparators={[',','，']}/></Form.Item><Form.Item name="misspellings" label="常见错误拼写"><Select mode="tags" tokenSeparators={[',','，']}/></Form.Item><Form.Item name="character_names" label="角色名"><Select mode="tags" tokenSeparators={[',','，']}/></Form.Item><Form.Item name="custom_queries" label="自定义搜索词"><Select mode="tags" tokenSeparators={[',','，']}/></Form.Item><Form.Item name="regions" label="监测国家"><Select mode="tags" options={['US','CA','GB','AU','SG'].map(value=>({value,label:value}))}/></Form.Item><Form.Item name="languages" label="监测语言"><Select mode="tags" options={['en','es','pt','fr','de'].map(value=>({value,label:value}))}/></Form.Item></div>
   {profile?.queries.length?<div className="radar-query-list"><span>搜索词（默认最多启用 8 个）</span><Checkbox.Group value={enabledQueryIds} onChange={values=>setEnabledQueryIds(values.map(Number).slice(0,8))}>{profile.queries.map(item=><Checkbox key={item.id} value={item.id}>{item.query_text}</Checkbox>)}</Checkbox.Group></div>:null}
   {profile?.last_error&&<Alert type="error" showIcon message={profile.last_error}/>}<div className="radar-profile-foot"><div>{profile?.last_scanned_at?<Tag color="green">上次监测 {new Date(profile.last_scanned_at).toLocaleString('zh-CN')}</Tag>:<Tag>尚未监测</Tag>}<Tag>{enabledQueryIds.length} 个启用搜索词</Tag></div><Button type="primary" htmlType="submit" icon={<SaveOutlined/>} loading={saving}>保存配置</Button></div>
  </Form>
 </Card>
}
