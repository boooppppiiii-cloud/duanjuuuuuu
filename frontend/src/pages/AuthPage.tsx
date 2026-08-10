import { useState } from 'react'
import { Button,Form,Input,message,Segmented,Typography } from 'antd'
import { LockOutlined,MailOutlined } from '@ant-design/icons'
import { api,type AuthUser } from '../api'
import { JushuLogo } from '../components/JushuLogo'

export default function AuthPage({onAuthenticated}:{onAuthenticated:(user:AuthUser)=>void}){
 const[mode,setMode]=useState<'login'|'register'>('login')
 const[busy,setBusy]=useState(false)
 const[msg,holder]=message.useMessage()
 const submit=async(values:{email:string;password:string})=>{
  setBusy(true)
  try{const result=mode==='login'?await api.login(values.email,values.password):await api.register(values.email,values.password);onAuthenticated(result.user);msg.success(mode==='login'?'登录成功':'账号已建立')}
  catch(error){msg.error((error as Error).message)}finally{setBusy(false)}
 }
 return <main className="auth-page">{holder}<section className="auth-panel">
  <div className="auth-brand"><JushuLogo size={48}/><div><b>剧枢</b><span>DRAMA OPS HUB</span></div></div>
  <Segmented block value={mode} onChange={value=>setMode(value as typeof mode)} options={[{label:'登录',value:'login'},{label:'注册',value:'register'}]}/>
  <div className="auth-title"><Typography.Title level={2}>{mode==='login'?'欢迎回来':'建立运营账号'}</Typography.Title></div>
  <Form layout="vertical" onFinish={submit} requiredMark={false}>
   <Form.Item name="email" label="邮箱" rules={[{required:true,message:'请输入邮箱'},{type:'email',message:'请输入有效邮箱'}]}><Input size="large" prefix={<MailOutlined/>} autoComplete="email" placeholder="name@company.com"/></Form.Item>
   <Form.Item name="password" label="密码" rules={[{required:true,message:'请输入密码'},{min:8,message:'密码至少 8 位'}]}><Input.Password size="large" prefix={<LockOutlined/>} autoComplete={mode==='login'?'current-password':'new-password'} placeholder="至少 8 位"/></Form.Item>
   <Button block size="large" type="primary" htmlType="submit" loading={busy}>{mode==='login'?'登录剧枢':'注册并登录'}</Button>
  </Form>
 </section></main>
}
