import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Empty, Progress, Segmented, Space, Statistic, Table, Tag, Typography, message } from 'antd'
import { ArrowRightOutlined, BarChartOutlined, ReloadOutlined, RocketOutlined, TeamOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, Account, Post, PublishJob, WorkspaceSummary } from '../api'
import Engagement from './Engagement'

const fmt=(n:number)=>new Intl.NumberFormat('zh-CN').format(n||0)
const statusMeta:Record<string,[string,string]>={queued:['待排期','blue'],uploading:['上传中','processing'],submitted:['平台处理中','gold'],published:['已发布','green'],failed:['失败','red'],blocked:['已阻止','orange']}

export default function DashboardPage(){
  const[data,setData]=useState<WorkspaceSummary>()
  const[jobs,setJobs]=useState<PublishJob[]>([])
  const[accounts,setAccounts]=useState<Account[]>([])
  const[posts,setPosts]=useState<Post[]>([])
  const[loading,setLoading]=useState(false)
  const[activeSection,setActiveSection]=useState<'accounts'|'publishing'|'fans'>('accounts')
  const[msg,holder]=message.useMessage()
  const navigate=useNavigate()
  const load=async()=>{setLoading(true);try{const[summary,jobRows,accountRows,postRows]=await Promise.all([api.workspaceSummary(),api.publishJobs(),api.accounts(),api.posts()]);setData(summary);setJobs(jobRows);setAccounts(accountRows);setPosts(postRows)}catch(e){msg.error((e as Error).message)}finally{setLoading(false)}}
  useEffect(()=>{void load()},[])
  const publishCounts=useMemo(()=>({queued:jobs.filter(x=>x.status==='queued').length,processing:jobs.filter(x=>['uploading','submitted'].includes(x.status)).length,published:jobs.filter(x=>x.status==='published').length,failed:jobs.filter(x=>['failed','blocked'].includes(x.status)).length}),[jobs])

  return <div className="workspace-page overview-page">{holder}
    <div className="page-heading page-heading-rich"><Typography.Title level={2}>账号总览</Typography.Title><Button icon={<ReloadOutlined/>} loading={loading} onClick={load}>刷新全部数据</Button></div>

    <div className="overview-pager-row">
      <Segmented
        block
        className="overview-pager"
        value={activeSection}
        onChange={value=>setActiveSection(value as typeof activeSection)}
        options={[
          {value:'accounts',label:'账号数据汇总'},
          {value:'publishing',label:'发布内容总览'},
          {value:'fans',label:'粉丝运营'},
        ]}
      />
    </div>

    {activeSection==='accounts'&&<section className="overview-section">
      <div className="section-heading"><div><span className="section-index">01</span><Typography.Title level={3}>账号数据汇总</Typography.Title></div><Button type="link" onClick={()=>navigate('/management')}>管理账号 <ArrowRightOutlined/></Button></div>
      <div className="summary-strip overview-account-summary"><Statistic title="账号总数" value={data?.kpis.accounts||0} prefix={<TeamOutlined/>}/><Statistic title="已连接" value={data?.kpis.connected_accounts||0}/><Statistic title="近 7 天播放" value={fmt(data?.kpis.views_7d||0)}/><Statistic title="近 7 天评论" value={fmt(data?.kpis.comments_7d||0)}/></div>
      <Card className="table-card" styles={{body:{padding:0}}}><Table size="small" rowKey="id" pagination={false} dataSource={data?.matrix.slice(0,8)} locale={{emptyText:<Empty description="尚未连接真实平台账号"/>}} scroll={{x:850}} columns={[
        {title:'平台',dataIndex:'platform',render:(x:string)=><Tag>{x.toUpperCase()}</Tag>},{title:'账号',dataIndex:'name',render:(x:string,r)=><div><b>{x}</b><div className="cell-sub">{r.account_type==='official'?'官方账号':'达人账号'}</div></div>},{title:'连接',dataIndex:'status',render:(x:string)=><Tag color={x==='connected'?'green':'orange'}>{x==='connected'?'已连接':'未连接'}</Tag>},{title:'近 7 天发布',dataIndex:'posts_7d'},{title:'近 7 天播放',dataIndex:'views_7d',render:fmt},{title:'互动',render:(_,r)=>fmt(r.likes_7d+r.comments_7d)},{title:'粉丝',dataIndex:'followers',render:fmt},{title:'账号健康',render:(_,r)=><Progress percent={r.failed_total?60:100} status={r.failed_total?'exception':'success'} size="small" showInfo={false}/>} ]}/></Card>
    </section>}

    {activeSection==='publishing'&&<section className="overview-section">
      <div className="section-heading"><div><span className="section-index">02</span><Typography.Title level={3}>发布内容总览</Typography.Title></div><Space><Button onClick={()=>navigate('/factory')}>进入内容工厂</Button><Button type="primary" icon={<RocketOutlined/>} onClick={()=>navigate('/publishing')}>进入一键发布</Button></Space></div>
      <div className="summary-strip publishing-overview"><Statistic title="待编辑成品" value={data?.kpis.ready_posts||0}/><Statistic title="等待排期" value={publishCounts.queued}/><Statistic title="平台处理中" value={publishCounts.processing}/><Statistic title="已发布" value={publishCounts.published}/><Statistic title="失败 / 阻止" value={publishCounts.failed} valueStyle={{color:publishCounts.failed?'#c2413b':undefined}}/></div>
      <div className="overview-publish-grid"><Card title="内容流转"><div className="workflow-track">{[['本地剧目',data?.workflow.source||0],['内容处理中',data?.workflow.processing||0],['待终审',data?.workflow.review||0],['待发布',data?.workflow.ready||0],['已发布',data?.workflow.published||0]].map(([label,value],index)=><div className="workflow-node static" key={String(label)}><span>{index+1}</span><b>{label}</b><strong>{value}</strong></div>)}</div></Card><Card className="table-card" title="最近发布任务" styles={{body:{padding:0}}}><Table size="small" rowKey="id" pagination={false} dataSource={jobs.slice(0,6)} locale={{emptyText:'暂无真实发布任务'}} columns={[{title:'成品',dataIndex:'post_id',ellipsis:true,render:(id:number)=>posts.find(x=>x.id===id)?.title||`#${id}`},{title:'账号',dataIndex:'account_id',render:(id:number)=>accounts.find(x=>x.id===id)?.name||`#${id}`},{title:'状态',dataIndex:'status',render:(x:string)=>{const meta=statusMeta[x]||[x,'default'];return <Tag color={meta[1]}>{meta[0]}</Tag>}},{title:'时间',dataIndex:'scheduled_at',render:(x:string)=>new Date(x).toLocaleString()}]}/></Card></div>
      {(data?.alerts.failed_jobs||0)>0&&<Alert type="warning" showIcon message={`${data?.alerts.failed_jobs} 个发布任务需要处理`}/>}
    </section>}

    {activeSection==='fans'&&<section className="overview-section fan-section">
      <div className="section-heading"><div><span className="section-index">03</span><Typography.Title level={3}>粉丝运营</Typography.Title></div><Tag icon={<BarChartOutlined/>}>评论区舆情</Tag></div>
      <Engagement embedded/>
    </section>}
  </div>
}
