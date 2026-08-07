import { useEffect, useMemo, useState } from 'react'
import { Button, Card, DatePicker, Empty, message, Space, Table, Tag, Typography } from 'antd'
import { CloudSyncOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import { api, type Dashboard, type Metric } from '../api'
import { SmoothLineChart } from '../components/SmoothLineChart'

const fmt=(value:number)=>new Intl.NumberFormat('zh-CN').format(value)
const compact=(value:number)=>new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:1}).format(value)

export default function Metrics(){
  const [rows,setRows]=useState<Metric[]>([])
  const [dashboard,setDashboard]=useState<Dashboard>()
  const [range,setRange]=useState<[Dayjs,Dayjs]>()
  const [loading,setLoading]=useState(false)
  const [collecting,setCollecting]=useState(false)
  const [msg,context]=message.useMessage()

  const load=async()=>{
    setLoading(true)
    try {
      const start=range?.[0].format('YYYY-MM-DD'), end=range?.[1].format('YYYY-MM-DD')
      const [metrics,summary]=await Promise.all([api.metrics(),api.dashboard(start,end)])
      setRows(metrics); setDashboard(summary)
    } finally { setLoading(false) }
  }

  useEffect(()=>{load().catch(e=>msg.error(e.message))},[])

  const collect=async()=>{
    setCollecting(true)
    try {
      const result=await api.collectMetrics()
      if(result.errors.length) msg.warning(`采集完成：新增 ${result.created} 条，${result.errors.length} 条失败；${result.errors[0].account||`任务 #${result.errors[0].job_id}`}：${result.errors[0].error}`)
      else msg.success(result.created ? `已从平台获取 ${result.created} 条新快照` : result.skipped?'今天的数据已经采集过':'暂无可采集的已发布内容')
      await load()
    } catch(e) { msg.error(e instanceof Error?e.message:'平台数据采集失败') }
    finally { setCollecting(false) }
  }

  const rawCols=[
    {title:'日期',dataIndex:'date'},
    {title:'成品',dataIndex:'post_title'},
    {title:'账号',render:(_:unknown,r:Metric)=><><b>{r.account_name}</b><div className="cell-sub">{r.account_type}</div></>},
    {title:'封面来源',dataIndex:'cover_fallback',render:(x:boolean)=><Tag color={x?'orange':'green'}>{x?'视频帧':'创意底图'}</Tag>},
    {title:'播放',dataIndex:'views'},
    {title:'涨粉',dataIndex:'followers'},
    {title:'点赞',dataIndex:'likes'},
    {title:'评论',dataIndex:'comments'},
  ]
  const accountTrends=useMemo(()=>{
    const grouped=new Map<string,NonNullable<Dashboard['account_trends']>>()
    for(const item of dashboard?.account_trends??[])grouped.set(item.account,[...(grouped.get(item.account)??[]),item])
    return [...grouped.entries()].map(([account,items])=>({account,items:[...items].sort((a,b)=>a.date.localeCompare(b.date))}))
  },[dashboard])
  return <div className="workspace-page">{context}
    <Space className="page-heading" align="start" wrap>
      <Typography.Title level={2}>数据中台</Typography.Title>
      <Space wrap>
        <DatePicker.RangePicker onChange={v=>setRange(v as [Dayjs,Dayjs])}/>
        <Button icon={<ReloadOutlined/>} loading={loading} onClick={()=>load().catch(e=>msg.error(e.message))}>筛选</Button>
        <Button type="primary" icon={<CloudSyncOutlined/>} loading={collecting} onClick={collect}>从平台采集</Button>
        <Button icon={<DownloadOutlined/>} href="/api/workspace/weekly.csv">导出账号周表</Button>
      </Space>
    </Space>
    <div className="creative-grid">
      <Card title="账号播放与涨粉趋势">{accountTrends.length?<div className="legacy-trend-chart-list">{accountTrends.map(group=><div className="legacy-trend-chart" key={group.account}><b>{group.account}</b><SmoothLineChart seriesName="播放量" valueFormat={compact} ariaLabel={`${group.account}播放趋势图`} points={group.items.map(item=>({label:item.date,axisLabel:item.date.slice(5),value:item.views,details:[{label:'播放量',value:fmt(item.views)},{label:'涨粉',value:fmt(item.followers)}]}))}/></div>)}</div>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="等待首次数据采集"/>}</Card>
      <Card title="剪辑模板 · 平均播放"><Table rowKey="template" pagination={false} dataSource={dashboard?.templates} locale={{emptyText:'暂无真实数据'}} columns={[{title:'模板',dataIndex:'template'},{title:'平均播放',dataIndex:'avg_views'},{title:'样本数',dataIndex:'count'}]}/></Card>
      <Card title="剧目 · 累计播放与最佳单条"><Table rowKey="drama" pagination={false} dataSource={dashboard?.dramas} locale={{emptyText:'暂无真实数据'}} columns={[{title:'剧目',dataIndex:'drama'},{title:'累计播放',dataIndex:'total_views'},{title:'最佳单条',dataIndex:'best_views'}]}/></Card>
      <Card title="创意底图与视频帧表现"><Table rowKey="kind" pagination={false} dataSource={dashboard?.covers} locale={{emptyText:'暂无真实数据'}} columns={[{title:'封面',dataIndex:'kind'},{title:'平均播放',dataIndex:'avg_views'},{title:'平均点赞',dataIndex:'avg_likes'},{title:'样本数',dataIndex:'count'}]}/></Card>
    </div>
    <Card title="平台数据快照"><Table loading={loading} rowKey="id" dataSource={rows} columns={rawCols} scroll={{x:850}} locale={{emptyText:'暂无真实数据'}}/></Card>
  </div>
}
