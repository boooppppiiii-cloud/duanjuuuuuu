import {
  CalendarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloudUploadOutlined,
  ExclamationCircleOutlined,
  LinkOutlined,
  ReloadOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Radio,
  Segmented,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { api, type Account, type IntegrationConfig, type Post, type PublishJob } from '../api'

const statusMeta:Record<string,{label:string;color:string}>={
  queued:{label:'等待排期',color:'blue'},uploading:{label:'正在上传',color:'processing'},submitted:{label:'平台处理中',color:'gold'},
  published:{label:'已发布',color:'success'},failed:{label:'失败',color:'error'},blocked:{label:'已阻止',color:'warning'},
}

export default function Publish({embedded=false}:{embedded?:boolean}){
  const [accounts,setAccounts]=useState<Account[]>([])
  const [posts,setPosts]=useState<Post[]>([])
  const [jobs,setJobs]=useState<PublishJob[]>([])
  const [integration,setIntegration]=useState<IntegrationConfig>()
  const [view,setView]=useState<'workbench'|'records'>('workbench')
  const [mode,setMode]=useState<'now'|'schedule'>('now')
  const [working,setWorking]=useState(false)
  const [checking,setChecking]=useState<number|null>(null)
  const [selectedAccounts,setSelectedAccounts]=useState<number[]>([])
  const [selectedPosts,setSelectedPosts]=useState<number[]>([])
  const [tiktokPrivacy,setTikTokPrivacy]=useState<string[]>([])
  const [form]=Form.useForm()
  const [msg,ctx]=message.useMessage()

  const load=async()=>{
    const [a,p,j,i]=await Promise.all([api.accounts(),api.posts(),api.publishJobs(),api.integrationConfig()])
    setAccounts(a);setPosts(p);setJobs(j);setIntegration(i)
  }
  useEffect(()=>{load().catch(e=>msg.error(e.message))},[])

  const connected=accounts.filter(x=>x.status==='connected')
  const selected=accounts.filter(x=>selectedAccounts.includes(x.id))
  const platforms=new Set(selected.map(x=>x.platform))
  const counts=useMemo(()=>({
    queued:jobs.filter(x=>x.status==='queued').length,
    processing:jobs.filter(x=>['uploading','submitted'].includes(x.status)).length,
    published:jobs.filter(x=>x.status==='published').length,
    failed:jobs.filter(x=>['failed','blocked'].includes(x.status)).length,
  }),[jobs])

  const changeAccounts=async(ids:number[])=>{
    setSelectedAccounts(ids)
    const tiktok=accounts.filter(x=>ids.includes(x.id)&&x.platform==='tiktok')
    if(!tiktok.length){setTikTokPrivacy([]);return}
    try{
      const info=await Promise.all(tiktok.map(x=>api.creatorInfo(x.id)))
      const intersection=info.map(x=>x.privacy_level_options).reduce((a,b)=>a.filter(x=>b.includes(x)))
      setTikTokPrivacy(intersection)
      if(intersection.length===1)form.setFieldValue('tiktok_privacy',intersection[0])
    }catch(e:any){setTikTokPrivacy([]);msg.error(e.message)}
  }

  const submit=async(v:any)=>{
    const postIds=v.post_ids as number[];const accountIds=v.account_ids as number[]
    const options:Record<string,unknown>={
      youtube_privacy:v.youtube_privacy||'private',made_for_kids:Boolean(v.made_for_kids),
      tiktok_privacy:v.tiktok_privacy,disable_duet:Boolean(v.disable_duet),disable_comment:Boolean(v.disable_comment),disable_stitch:Boolean(v.disable_stitch),
      facebook_published:v.facebook_published!==false,
      instagram_video_urls:Object.fromEntries(postIds.map(id=>[String(id),v[`instagram_url_${id}`]||''])),
    }
    const missingInstagram=platforms.has('instagram')&&!integration?.public_media_ready&&postIds.some(id=>!String(v[`instagram_url_${id}`]||'').startsWith('https://'))
    if(missingInstagram){msg.error('请填写每个视频的公网 HTTPS 地址，或完成 PUBLIC_MEDIA_BASE_URL 配置');return}
    if(platforms.has('tiktok')&&!v.tiktok_privacy){msg.error('请读取并选择 TikTok Creator Info 返回的可见性');return}
    const time=mode==='now'?new Date().toISOString():v.scheduled_at.toISOString()
    Modal.confirm({
      width:620,title:'确认提交到平台官方接口？',icon:<SafetyCertificateOutlined/>,okText:mode==='now'?'确认上传':'确认排期',
      content:<Descriptions bordered size="small" column={1} items={[{key:'count',label:'任务数量',children:`${postIds.length} 个成品 × ${accountIds.length} 个账号 = ${postIds.length*accountIds.length} 个任务`},{key:'accounts',label:'目标账号',children:selected.map(x=>`${x.name}（${x.platform}）`).join('、')},{key:'time',label:'执行时间',children:new Date(time).toLocaleString()},{key:'truth',label:'失败规则',children:'任何凭证、权限或平台错误都会记为失败，不会自动改成手工成功。'}]}/>,
      onOk:async()=>{setWorking(true);try{await api.batchPublish(postIds,accountIds,time,mode==='now',Boolean(v.ai_disclosure),options);msg.success(mode==='now'?'已向平台提交，请到任务记录查看真实结果':'排期已保存');form.resetFields();setSelectedAccounts([]);setSelectedPosts([]);await load();setView('records')}catch(e:any){msg.error(e.message)}finally{setWorking(false)}},
    })
  }

  const run=async(id:number)=>{setChecking(id);try{const result=await api.runPublishJob(id);if(result.status==='failed'||result.status==='blocked')msg.error(result.result_log);else msg.success('任务已提交平台');await load()}catch(e:any){msg.error(e.message)}finally{setChecking(null)}}
  const refresh=async(id:number)=>{setChecking(id);try{await api.refreshPublishJob(id);await load()}catch(e:any){msg.error(e.message)}finally{setChecking(null)}}

  const accountOptions=connected.map(x=>({value:x.id,label:`${x.platform.toUpperCase()} · ${x.name}`}))
  return <div className="workspace-page publish-page">{ctx}
    {embedded?<div className="module-toolbar"><b>普通社媒一键发布</b><Space><Segmented value={view} onChange={v=>setView(v as typeof view)} options={[{label:'发布工作台',value:'workbench',icon:<SendOutlined/>},{label:'任务记录',value:'records',icon:<ClockCircleOutlined/>}]}/><Button icon={<ReloadOutlined/>} onClick={()=>load()}>刷新</Button></Space></div>:<div className="page-heading page-heading-rich"><Typography.Title level={2}>一键发布</Typography.Title><Space><Segmented value={view} onChange={v=>setView(v as typeof view)} options={[{label:'发布工作台',value:'workbench',icon:<SendOutlined/>},{label:'任务记录',value:'records',icon:<ClockCircleOutlined/>}]}/><Button icon={<ReloadOutlined/>} onClick={()=>load()}>刷新</Button></Space></div>}

    <div className="summary-strip publish-summary"><Statistic title="等待排期" value={counts.queued}/><Statistic title="平台处理中" value={counts.processing}/><Statistic title="真实发布完成" value={counts.published}/><Statistic title="失败 / 阻止" value={counts.failed}/></div>

    {connected.length===0&&<Alert type="warning" showIcon message="没有可发布账号"/>} 

    {view==='workbench'?<div className="publish-layout-v2">
      <Card className="publish-composer" title="创建真实发布任务" extra={<Tag color="green">{connected.length} 个已连接账号</Tag>}>
        <Form form={form} layout="vertical" onFinish={submit} initialValues={{ai_disclosure:false,youtube_privacy:'private',facebook_published:true}}>
          <Form.Item name="post_ids" label="1. 选择成品" rules={[{required:true,message:'请选择至少一个成品'}]}><Select mode="multiple" optionFilterProp="label" onChange={setSelectedPosts} placeholder="支持多选" options={posts.map(x=>({value:x.id,label:`#${x.id} ${x.title}`}))}/></Form.Item>
          <Form.Item name="account_ids" label="2. 选择已连接账号" rules={[{required:true,message:'请选择至少一个账号'}]}><Select mode="multiple" optionFilterProp="label" onChange={changeAccounts} placeholder="未连接账号不会出现在这里" options={accountOptions}/></Form.Item>
          <Form.Item label="3. 执行方式"><Radio.Group value={mode} onChange={e=>setMode(e.target.value)} optionType="button" buttonStyle="solid" options={[{value:'now',label:'立即上传'},{value:'schedule',label:'定点排期'}]}/></Form.Item>
          {mode==='schedule'&&<Form.Item name="scheduled_at" label="计划时间" rules={[{required:true,message:'请选择时间'}]}><DatePicker showTime showNow disabledDate={d=>d.isBefore(dayjs().startOf('day'))}/></Form.Item>}

          {platforms.size>0&&<div className="platform-settings"><Typography.Title level={5}>4. 平台发布参数</Typography.Title>
            {platforms.has('youtube')&&<div className="platform-setting-row"><Tag color="red">YouTube</Tag><Form.Item name="youtube_privacy" label="可见性"><Select options={['private','unlisted','public'].map(x=>({value:x,label:x}))}/></Form.Item><Form.Item name="made_for_kids" label="儿童内容" valuePropName="checked"><Switch/></Form.Item></div>}
            {platforms.has('tiktok')&&<div className="platform-setting-block"><div className="platform-setting-row"><Tag>TikTok</Tag><Form.Item name="tiktok_privacy" label="Creator Info 允许的可见性" rules={[{required:true}]}><Select loading={selected.some(x=>x.platform==='tiktok')&&!tiktokPrivacy.length} options={tiktokPrivacy.map(x=>({value:x,label:x}))} placeholder="由平台实时返回"/></Form.Item></div><Space wrap><Form.Item name="disable_comment" valuePropName="checked"><Checkbox>关闭评论</Checkbox></Form.Item><Form.Item name="disable_duet" valuePropName="checked"><Checkbox>关闭 Duet</Checkbox></Form.Item><Form.Item name="disable_stitch" valuePropName="checked"><Checkbox>关闭 Stitch</Checkbox></Form.Item></Space></div>}
            {platforms.has('facebook')&&<div className="platform-setting-row"><Tag color="blue">Facebook</Tag><Form.Item name="facebook_published" label="立即公开" valuePropName="checked"><Switch/></Form.Item></div>}
            {platforms.has('instagram')&&<div className="platform-setting-block"><Space><Tag color="magenta">Instagram</Tag><Typography.Text type="secondary">{integration?.public_media_ready?'已配置临时 HTTPS 媒体地址，可直接发布；下方可选填外部 CDN 地址。':'请为每个成品填写公网 HTTPS 地址。'}</Typography.Text></Space>{selectedPosts.map(id=><Form.Item key={id} name={`instagram_url_${id}`} label={posts.find(x=>x.id===id)?.title||`成品 #${id}`} rules={[{required:!integration?.public_media_ready},{type:'url',message:'请输入完整 HTTPS 地址'}]}><Input prefix={<LinkOutlined/>} placeholder={integration?.public_media_ready?'可选：留空则由系统生成临时地址':'https://cdn.example.com/video.mp4'}/></Form.Item>)}</div>}
          </div>}

          <div className="publish-consent"><Form.Item name="ai_disclosure" valuePropName="checked" noStyle><Switch/></Form.Item><b>AI 内容标注</b></div>
          <Button size="large" block type="primary" htmlType="submit" loading={working} disabled={!connected.length} icon={mode==='now'?<RocketOutlined/>:<CalendarOutlined/>}>{mode==='now'?'检查并提交平台':'保存真实排期'}</Button>
        </Form>
      </Card>
      <aside className="publish-side-v2"><Card title="发布前检查"><ol className="clean-checklist"><li>账号已连接</li><li>成品已终审</li><li>可见性已选择</li><li>平台权限已开通</li></ol></Card></aside>
    </div>:<Card className="table-card" styles={{body:{padding:0}}}><Table rowKey="id" dataSource={jobs} scroll={{x:1250}} locale={{emptyText:<Empty description="暂无真实发布任务"/>}} columns={[
      {title:'任务',dataIndex:'id',width:75,render:(x:number)=>`#${x}`},{title:'账号',dataIndex:'account_id',width:180,render:(x:number)=>{const a=accounts.find(a=>a.id===x);return a?<><Tag>{a.platform}</Tag>{a.name}</>:`#${x}`}},
      {title:'成品',dataIndex:'post_id',width:220,ellipsis:true,render:(x:number)=>posts.find(p=>p.id===x)?.title||`#${x}`},{title:'计划时间',dataIndex:'scheduled_at',width:175,render:(x:string)=>new Date(x).toLocaleString()},
      {title:'状态',dataIndex:'status',width:130,render:(x:string)=>{const m=statusMeta[x]||{label:x,color:'default'};return <Tag color={m.color} icon={['uploading','submitted'].includes(x)?<SyncOutlined spin/>:undefined}>{m.label}</Tag>}},
      {title:'平台 ID / 链接',width:220,render:(_:unknown,r:PublishJob)=>r.platform_url?<a href={r.platform_url} target="_blank">{r.platform_video_id||'打开平台'}</a>:r.platform_video_id||'—'},
      {title:'真实结果',dataIndex:'result_log',ellipsis:true},{title:'重试',dataIndex:'retry_count',width:70},
      {title:'操作',fixed:'right' as const,width:175,render:(_:unknown,r:PublishJob)=><Space><Button size="small" loading={checking===r.id} disabled={!['queued','failed','blocked'].includes(r.status)} onClick={()=>run(r.id)} icon={<CheckCircleOutlined/>}>{r.status==='queued'?'执行':'重试'}</Button><Button size="small" loading={checking===r.id} disabled={r.status!=='submitted'} onClick={()=>refresh(r.id)} icon={<SyncOutlined/>}>查状态</Button></Space>},
    ]}/></Card>}
  </div>
}
