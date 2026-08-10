import { useEffect,useState } from 'react'
import { Alert,Button,Card,Form,Input,message,Space,Table,Tag,Typography } from 'antd'
import type { AccountStrategy } from '../api'
import { useAuth } from '../auth'
import { getLocalStrategies,saveLocalStrategy } from '../localStrategies'

type FormValues={name:string;history_text:string}

export default function Strategies({embedded=false}:{embedded?:boolean}){
 const{user}=useAuth();const[items,setItems]=useState<AccountStrategy[]>([]);const[editing,setEditing]=useState<AccountStrategy>();const[msg,holder]=message.useMessage();const[form]=Form.useForm<FormValues>()
 const load=()=>setItems(getLocalStrategies(user.id))
 useEffect(load,[user.id])
 const edit=(item:AccountStrategy)=>{setEditing(item);form.setFieldsValue({name:item.name,history_text:item.history_text})}
 const cancel=()=>{setEditing(undefined);form.resetFields()}
 const save=(values:FormValues)=>{try{saveLocalStrategy(user.id,{name:values.name.trim(),history_text:values.history_text.trim(),confirmed:true},editing?.id);msg.success('过往文案已保存，可在一键发布时选择');cancel();load()}catch(e){msg.error((e as Error).message)}}
 const columns=[
  {title:'参考名称',dataIndex:'name',width:220,render:(value:string,row:AccountStrategy)=><Space>{value}{row.builtin&&<Tag>旧版</Tag>}</Space>},
  {title:'过往标题与文案',dataIndex:'history_text',ellipsis:true,render:(value:string)=><Typography.Text type={value?'secondary':'warning'}>{value||'旧策略没有保存过往文案，请编辑补充'}</Typography.Text>},
  {title:'内容量',width:100,render:(_:unknown,row:AccountStrategy)=>`${row.history_text.length} 字`},
  {title:'操作',width:90,render:(_:unknown,row:AccountStrategy)=><Button onClick={()=>edit(row)}>编辑</Button>},
 ]
 return <div className={embedded?'management-inner':'workspace-page'}>{holder}
  {!embedded&&<Typography.Title level={2}>账号运营策略</Typography.Title>}
  <Alert showIcon type="info" message="这里只保存你账号过往发布的标题和文案。AI 撰写时会模仿这些样本，并结合当前短剧的剧名、剧情简介重新创作。"/>
  <div className="creative-grid">
   <Card title={editing?`编辑：${editing.name}`:'录入过往发布内容'}>
    <Form form={form} layout="vertical" onFinish={save}>
     <Form.Item name="name" label="参考名称" rules={[{required:true,message:'请输入参考名称'}]}><Input placeholder="例如：FlickReels 英文 YouTube 账号"/></Form.Item>
     <Form.Item name="history_text" label="过往发布的标题与文案" extra="可以一次粘贴多条标题、视频简介和标签，保留原有换行即可。" rules={[{required:true,message:'请粘贴过往标题或文案'},{min:10,message:'样本太短，请至少输入 10 个字符'}]}><Input.TextArea rows={16} placeholder={'示例：\n【HOT】I Faked Death 7 Years Ago... #FlickReels\n\n🎬 Title: 【The Name We Buried】\n剧情简介与历史标签……'}/></Form.Item>
     <Space><Button type="primary" htmlType="submit">保存</Button>{editing&&<Button onClick={cancel}>取消</Button>}</Space>
    </Form>
   </Card>
   <Card title={`已保存的文案参考（${items.length}）`}><Table rowKey="id" dataSource={items} columns={columns} pagination={false}/></Card>
  </div>
 </div>
}
