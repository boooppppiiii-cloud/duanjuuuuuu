import {
  ApiOutlined,
  CheckCircleFilled,
  CloudSyncOutlined,
  CopyOutlined,
  DisconnectOutlined,
  DownloadOutlined,
  EditOutlined,
  ExclamationCircleFilled,
  EyeOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Avatar,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Radio,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import {
  api,
  type Account,
  type AccountMatrixRow,
  type AccountStrategy,
  type IntegrationConfig,
} from '../api'
import { PlatformBadge, PlatformLogo, PlatformOption } from '../components/PlatformBrand'

type Platform = 'youtube' | 'tiktok' | 'instagram' | 'facebook'
type OAuthPlatform = 'youtube' | 'meta' | 'tiktok'
type MediaRow = { id:string;title:string;published_at:string|null;views:number;likes:number;comments:number;url:string }

const fmt = (n:number) => new Intl.NumberFormat('zh-CN').format(n)
const platformOptions:Platform[] = ['youtube','tiktok','instagram','facebook']

function connectionTag(status:string){
  if(status==='connected') return <Tag color="success" icon={<CheckCircleFilled/>}>已连接</Tag>
  if(status==='error') return <Tag color="error" icon={<ExclamationCircleFilled/>}>连接异常</Tag>
  if(status==='disabled') return <Tag>已停用</Tag>
  return <Tag color="warning">未连接</Tag>
}

export default function Matrix({embedded=false}:{embedded?:boolean}){
  const [rows,setRows]=useState<AccountMatrixRow[]>([])
  const [accounts,setAccounts]=useState<Account[]>([])
  const [strategies,setStrategies]=useState<AccountStrategy[]>([])
  const [integration,setIntegration]=useState<IntegrationConfig|null>(null)
  const [section,setSection]=useState<'accounts'|'apps'>('accounts')
  const [accountOpen,setAccountOpen]=useState(false)
  const [appOpen,setAppOpen]=useState<OAuthPlatform|null>(null)
  const [editing,setEditing]=useState<Account|null>(null)
  const [working,setWorking]=useState<number|null>(null)
  const [mediaAccount,setMediaAccount]=useState<Account|null>(null)
  const [media,setMedia]=useState<MediaRow[]>([])
  const [mediaLoading,setMediaLoading]=useState(false)
  const [accountForm]=Form.useForm()
  const [appForm]=Form.useForm()
  const [msg,ctx]=message.useMessage()

  const load=async()=>{
    const [matrix,accountList,strategyList,config]=await Promise.all([api.accountMatrix(),api.accounts(),api.strategies(),api.integrationConfig()])
    setRows(matrix);setAccounts(accountList);setStrategies(strategyList);setIntegration(config)
  }
  useEffect(()=>{
    load().catch(e=>msg.error(e.message))
    const params=new URLSearchParams(window.location.search)
    if(params.get('oauth')==='success'){
      const notice={type:'lingshu-oauth-complete',platform:params.get('platform'),accounts:params.get('accounts')}
      if(window.opener){window.opener.postMessage(notice,window.location.origin);window.setTimeout(()=>window.close(),700)}
      else msg.success(`${params.get('platform')||'平台'} 授权完成，已连接 ${params.get('accounts')||'1'} 个账号`)
      window.history.replaceState({},'',window.location.pathname)
    }
    const receive=(event:MessageEvent)=>{if(event.origin===window.location.origin&&event.data?.type==='lingshu-oauth-complete'){msg.success('平台授权完成，正在刷新账号');load().catch(e=>msg.error(e.message))}}
    window.addEventListener('message',receive)
    return()=>window.removeEventListener('message',receive)
  },[])

  const totals=useMemo(()=>({
    connected:rows.filter(x=>x.status==='connected').length,
    views:rows.reduce((a,b)=>a+b.views_7d,0),
    posts:rows.reduce((a,b)=>a+b.posts_7d,0),
    errors:rows.filter(x=>x.status==='error').length,
  }),[rows])

  const openAccount=(account?:Account)=>{
    setEditing(account||null)
    accountForm.resetFields()
    if(account){
      const c=account.credential_status
      accountForm.setFieldsValue({
        platform:account.platform,name:account.name,account_type:account.account_type,strategy_id:account.strategy_id,
        channel_id:c.channel_id,page_id:c.page_id,ig_user_id:c.ig_user_id,graph_version:c.graph_version,
        access_token_env:c.access_token_env,refresh_token_env:c.refresh_token_env,client_id_env:c.client_id_env,client_secret_env:c.client_secret_env,
        default_privacy:c.default_privacy||'private',app_link:c.app_link||'',
      })
    }else accountForm.setFieldsValue({platform:'youtube',account_type:'official',default_privacy:'private'})
    setAccountOpen(true)
  }

  const saveAccount=async(v:any)=>{
    const platform=v.platform as Platform
    const publicConfig:Record<string,string>={}
    if(platform==='youtube'){publicConfig.channel_id=v.channel_id||'';publicConfig.default_privacy=v.default_privacy||'private'}
    if(platform==='facebook'){publicConfig.page_id=v.page_id||'';publicConfig.graph_version=v.graph_version||''}
    if(platform==='instagram'){publicConfig.ig_user_id=v.ig_user_id||'';publicConfig.page_id=v.page_id||'';publicConfig.graph_version=v.graph_version||''}
    if(platform==='tiktok') publicConfig.open_id=v.open_id||''
    publicConfig.app_link=v.app_link||''
    const secrets:Record<string,string>={access_token:v.access_token||'',refresh_token:v.refresh_token||'',client_id:v.client_id||'',client_secret:v.client_secret||''}
    const secretEnvs:Record<string,string>={access_token:v.access_token_env||'',refresh_token:v.refresh_token_env||'',client_id:v.client_id_env||'',client_secret:v.client_secret_env||''}
    await api.configureAccount({platform,name:v.name,account_type:v.account_type,strategy_id:v.strategy_id,public_config:publicConfig,secrets,secret_envs:secretEnvs},editing?.id)
    const hasStoredToken=Boolean(editing?.credential_status.access_token_set||editing?.credential_status.access_token_env)
    const oauthPlatform:OAuthPlatform|null=platform==='youtube'||platform==='tiktok'?platform:null
    const needsOAuth=Boolean(oauthPlatform)&&!v.access_token&&!v.access_token_env&&!hasStoredToken
    const oauthAppSaved=Boolean(needsOAuth&&v.client_id&&v.client_secret)
    if(oauthAppSaved&&oauthPlatform){
      await api.saveIntegrationConfig(oauthPlatform,{client_id:v.client_id,client_secret:v.client_secret})
      setSection('apps')
    }
    setAccountOpen(false)
    msg.success(oauthAppSaved?'开发者应用已保存，请点击“连接账号”完成授权':needsOAuth?'账号已保存；请在“开发者应用与 OAuth”完成授权':'账号配置已保存，请执行连接检测')
    await load()
  }

  const check=async(account:Account)=>{
    setWorking(account.id)
    try{await api.checkAccount(account.id);msg.success(`${account.name} 连接检测通过`);await load()}
    catch(e:any){msg.error(e.message);await load()}
    finally{setWorking(null)}
  }

  const disconnect=async(account:Account)=>{
    Modal.confirm({title:`断开 ${account.name}？`,content:'应用内加密保存的令牌会被清除，历史发布与数据仍保留。',okText:'确认断开',okButtonProps:{danger:true},onOk:async()=>{await api.disconnectAccount(account.id);msg.success('账号已断开');await load()}})
  }

  const showMedia=async(account:Account)=>{
    setMediaAccount(account);setMedia([]);setMediaLoading(true)
    try{setMedia(await api.accountMedia(account.id))}catch(e:any){msg.error(e.message)}finally{setMediaLoading(false)}
  }

  const saveApp=async(v:any)=>{
    if(!appOpen)return
    await api.saveIntegrationConfig(appOpen,{client_id:v.client_id,client_secret:v.client_secret})
    setAppOpen(null);msg.success('开发者应用配置已加密保存');await load()
  }

  const connectOAuth=async(platform:OAuthPlatform)=>{
    try{
      const result=await api.startOAuth(platform)
      const popup=window.open(result.authorization_url,`oauth-${platform}`,'popup,width=720,height=780')
      if(!popup) throw new Error('浏览器阻止了授权窗口，请允许本站弹窗后重试')
      msg.info('请在新窗口完成平台授权，完成后账号列表会自动刷新')
    }catch(e:any){msg.error(e.message)}
  }

  const selectedPlatform=Form.useWatch('platform',accountForm) as Platform|undefined
  const appCards:(readonly [OAuthPlatform,string,string])[]=[
    ['youtube','OAuth Web Application','Google Cloud Console'],['meta','多账号通用应用','Business Login + Graph API'],['tiktok','Login Kit 应用','Content Posting API'],
  ]

  const columns=[
    {title:'账号',width:260,render:(_:unknown,r:AccountMatrixRow)=>{
      const account=accounts.find(x=>x.id===r.id)
      return <Space><Avatar size={40} src={account?.avatar_url} icon={<PlatformLogo platform={r.platform} size={21}/>}/><div><Space size={6}><PlatformBadge platform={r.platform}/><b>{r.name}</b></Space><div className="cell-sub">{r.account_type==='official'?'官方账号':'达人账号'} · {r.profile_url?<a href={r.profile_url} target="_blank">打开主页</a>:'未读取主页'}</div></div></Space>
    }},
    {title:'真实连接',width:150,render:(_:unknown,r:AccountMatrixRow)=><div>{connectionTag(r.status)}<div className="cell-sub">{r.last_checked_at?`检查 ${new Date(r.last_checked_at).toLocaleString()}`:'尚未检测'}</div></div>},
    {title:'近7天',width:180,render:(_:unknown,r:AccountMatrixRow)=><div><b>{fmt(r.views_7d)} 播放</b><div className="cell-sub">{r.posts_7d} 发布 · {fmt(r.likes_7d)} 赞 · {fmt(r.comments_7d)} 评论</div></div>},
    {title:'累计成功',dataIndex:'published_total',width:90},
    {title:'粉丝',dataIndex:'followers',width:100,render:fmt},
    {title:'状态说明',dataIndex:'last_error',ellipsis:true,render:(x:string)=>x?<Typography.Text type="danger">{x}</Typography.Text>:<Typography.Text type="secondary">正常</Typography.Text>},
    {title:'操作',fixed:'right' as const,width:245,render:(_:unknown,r:AccountMatrixRow)=>{
      const account=accounts.find(x=>x.id===r.id);if(!account)return null
      return <Space wrap><Button size="small" icon={<CloudSyncOutlined/>} loading={working===r.id} onClick={()=>check(account)}>检测</Button><Button size="small" icon={<EyeOutlined/>} disabled={r.status!=='connected'} onClick={()=>showMedia(account)}>动态</Button><Button size="small" icon={<EditOutlined/>} onClick={()=>openAccount(account)}>配置</Button><Button size="small" danger icon={<DisconnectOutlined/>} disabled={r.status==='not_connected'} onClick={()=>disconnect(account)}>断开</Button></Space>
    }},
  ]

  return <div className="workspace-page account-center">{ctx}
    {embedded?<div className="module-toolbar"><b>账号连接与平台授权</b><Space><Button icon={<DownloadOutlined/>} href="/api/workspace/weekly.csv">导出周表</Button><Button icon={<ReloadOutlined/>} onClick={()=>load()}>刷新状态</Button><Button type="primary" icon={<PlusOutlined/>} onClick={()=>openAccount()}>配置账号</Button></Space></div>:<div className="page-heading page-heading-rich"><Typography.Title level={2}>账号与平台连接</Typography.Title><Space><Button icon={<DownloadOutlined/>} href="/api/workspace/weekly.csv">导出周表</Button><Button icon={<ReloadOutlined/>} onClick={()=>load()}>刷新状态</Button><Button type="primary" icon={<PlusOutlined/>} onClick={()=>openAccount()}>手动配置账号</Button></Space></div>}


    <div className="summary-strip account-summary"><Statistic title="账号总数" value={rows.length}/><Statistic title="已连接" value={totals.connected}/><Statistic title="近 7 天真实播放" value={fmt(totals.views)}/><Statistic title="连接异常" value={totals.errors}/></div>

    <Segmented className="section-switch" value={section} onChange={v=>setSection(v as typeof section)} options={[{label:'账号矩阵',value:'accounts',icon:<ApiOutlined/>},{label:'开发者应用与 OAuth',value:'apps',icon:<SettingOutlined/>}]}/>

    {section==='accounts'?<Card className="table-card account-table" styles={{body:{padding:0}}}>
      <Table rowKey="id" dataSource={rows} columns={columns} scroll={{x:1280}} pagination={{pageSize:10,showSizeChanger:false}} locale={{emptyText:<Empty description="还没有真实账号，请先连接平台或手动配置"/>}}/>
    </Card>:<div className="integration-grid">
      {appCards.map(([key,title,sub])=>{const app=integration?.apps[key];const ready=Boolean(app?.client_id&&app.client_secret_set);return <Card key={key} className="integration-card">
        <div className="integration-card-head"><Avatar className="integration-brand-avatar" shape="square" size={42} icon={<PlatformLogo platform={key} size={25}/>}/><div><b>{title}</b><p>{sub}</p></div>{ready?<Tag color="success">应用已配置</Tag>:<Tag color="warning">待配置</Tag>}</div>
        <Descriptions size="small" column={1} items={[{key:'id',label:'Client / App ID',children:app?.client_id||'未填写'},{key:'secret',label:'Secret',children:app?.client_secret_set?'已加密保存':'未填写'}]}/>
        <div className="callback-box"><span>Authorized redirect URI</span><code>{integration?.callbacks[key]}</code><Button size="small" type="text" icon={<CopyOutlined/>} onClick={()=>navigator.clipboard.writeText(integration?.callbacks[key]||'')}/></div>
        {!integration?.vault_ready&&<Alert type="warning" showIcon message="先在 .env 配置 CREDENTIAL_SECRET"/>}
        <Space className="integration-actions"><Button icon={<SettingOutlined/>} onClick={()=>{setAppOpen(key);appForm.setFieldsValue({client_id:app?.client_id,client_secret:''})}}>配置应用</Button><Button type="primary" icon={<LinkOutlined/>} disabled={!ready||!integration?.vault_ready} onClick={()=>connectOAuth(key)}>连接账号</Button></Space>
      </Card>})}
    </div>}

    <Modal width={700} open={accountOpen} title={editing?`配置账号 · ${editing.name}`:'手动配置真实账号'} footer={null} onCancel={()=>setAccountOpen(false)} destroyOnHidden>
      {!integration?.vault_ready&&<Alert className="modal-note" type="warning" showIcon message="尚未配置 CREDENTIAL_SECRET"/>}
      <Form form={accountForm} layout="vertical" onFinish={saveAccount}>
        <Alert className="modal-note" type="info" showIcon message="推荐使用 OAuth 自动获取 Access Token" description="如果没有现成的 Access Token，填写 Client ID 和 Client Secret 后保存，系统会切换到 OAuth 授权入口。"/>
        <div className="form-grid"><Form.Item name="platform" label="平台" rules={[{required:true}]}><Select disabled={Boolean(editing)} options={platformOptions.map(value=>({value,label:<PlatformOption platform={value}/> }))}/></Form.Item><Form.Item name="name" label="内部显示名称" rules={[{required:true}]}><Input placeholder="例如：北美女频主号"/></Form.Item></div>
        <div className="form-grid"><Form.Item name="account_type" label="账号类型"><Radio.Group options={[{label:'官方账号',value:'official'},{label:'达人账号',value:'creator'}]}/></Form.Item><Form.Item name="strategy_id" label="运营策略"><Select allowClear options={strategies.map(x=>({value:x.id,label:x.name}))}/></Form.Item></div>
        {selectedPlatform==='youtube'&&<div className="form-grid"><Form.Item name="channel_id" label="Channel ID"><Input placeholder="UC...；留空时通过 OAuth 读取 mine"/></Form.Item><Form.Item name="default_privacy" label="默认可见性"><Select options={['private','unlisted','public'].map(x=>({value:x,label:x}))}/></Form.Item></div>}
        {selectedPlatform==='facebook'&&<div className="form-grid"><Form.Item name="page_id" label="Facebook Page ID" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="graph_version" label="Graph API 版本"><Input placeholder="留空使用系统版本"/></Form.Item></div>}
        {selectedPlatform==='instagram'&&<><div className="form-grid"><Form.Item name="ig_user_id" label="Instagram Professional Account ID" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="page_id" label="关联 Facebook Page ID"><Input/></Form.Item></div><Form.Item name="graph_version" label="Graph API 版本"><Input placeholder="留空使用系统版本"/></Form.Item></>}
        {selectedPlatform==='tiktok'&&<Form.Item name="open_id" label="TikTok Open ID"><Input placeholder="OAuth 连接时自动读取"/></Form.Item>}
        <Form.Item name="app_link" label="官方观看链接" tooltip="官方号文案中的 {app_link} 会在发布时按账号替换；达人号可留空"><Input placeholder="https://your-app.example.com/series"/></Form.Item>
        <Typography.Title level={5}>授权令牌</Typography.Title>
        <div className="form-grid"><Form.Item name="access_token" label="Access Token（加密保存）"><Input.Password disabled={!integration?.vault_ready} autoComplete="new-password" placeholder={editing?.credential_status.access_token_set?'已保存；留空不修改':'粘贴真实令牌'}/></Form.Item><Form.Item name="access_token_env" label="或 Access Token 环境变量名"><Input placeholder="例如 YOUTUBE_ACCESS_TOKEN"/></Form.Item></div>
        {(selectedPlatform==='youtube'||selectedPlatform==='tiktok')&&<><div className="form-grid"><Form.Item name="refresh_token" label="Refresh Token（加密保存）"><Input.Password disabled={!integration?.vault_ready} autoComplete="new-password" placeholder={editing?.credential_status.refresh_token_set?'已保存；留空不修改':'建议填写，避免令牌到期'}/></Form.Item><Form.Item name="refresh_token_env" label="或 Refresh Token 环境变量名"><Input/></Form.Item></div><div className="form-grid"><Form.Item name="client_id" label="Client ID（加密保存）"><Input.Password disabled={!integration?.vault_ready} autoComplete="new-password"/></Form.Item><Form.Item name="client_id_env" label="或 Client ID 环境变量名"><Input/></Form.Item></div><div className="form-grid"><Form.Item name="client_secret" label="Client Secret（加密保存）"><Input.Password disabled={!integration?.vault_ready} autoComplete="new-password"/></Form.Item><Form.Item name="client_secret_env" label="或 Client Secret 环境变量名"><Input/></Form.Item></div></>}
        <Button block size="large" type="primary" htmlType="submit">保存配置并返回检测</Button>
      </Form>
    </Modal>

    <Modal open={Boolean(appOpen)} title={<Space>{appOpen&&<PlatformLogo platform={appOpen}/>}<span>配置开发者应用</span></Space>} footer={null} onCancel={()=>setAppOpen(null)} destroyOnHidden>
      <Form form={appForm} layout="vertical" onFinish={saveApp}><Form.Item name="client_id" label="Client ID / App ID / Client Key" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="client_secret" label="Client Secret / App Secret" rules={[{required:!integration?.apps[appOpen||'youtube']?.client_secret_set}]}><Input.Password autoComplete="new-password" placeholder={integration?.apps[appOpen||'youtube']?.client_secret_set?'已保存；留空表示不修改':''}/></Form.Item><Button block type="primary" htmlType="submit">加密保存</Button></Form>
    </Modal>

    <Drawer width={720} open={Boolean(mediaAccount)} title={`${mediaAccount?.name||''} · 平台动态`} onClose={()=>setMediaAccount(null)}>
      <Table loading={mediaLoading} rowKey="id" dataSource={media} pagination={false} locale={{emptyText:<Empty description="平台没有返回内容"/>}} columns={[{title:'内容',dataIndex:'title',ellipsis:true,render:(x:string,r:MediaRow)=>r.url?<a href={r.url} target="_blank">{x||r.id}</a>:x||r.id},{title:'发布时间',dataIndex:'published_at',render:(x:string|null)=>x?new Date(x).toLocaleString():'—'},{title:'播放',dataIndex:'views',render:fmt},{title:'点赞',dataIndex:'likes',render:fmt},{title:'评论',dataIndex:'comments',render:fmt}]}/>
    </Drawer>
  </div>
}
