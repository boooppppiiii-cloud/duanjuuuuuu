import { useEffect,useMemo,useState } from 'react'
import { Card,Empty,Segmented,Spin,Statistic,Table,Tag,Typography } from 'antd'
import { ApiOutlined,CloudServerOutlined,TeamOutlined,ThunderboltOutlined } from '@ant-design/icons'
import { api,type AdminAnalytics } from '../api'

const compact=(value:number)=>new Intl.NumberFormat('zh-CN',{notation:value>=10000?'compact':'standard',maximumFractionDigits:1}).format(value)
const bytes=(value:number)=>value>=1024**3?`${(value/1024**3).toFixed(1)} GB`:`${(value/1024**2).toFixed(1)} MB`

function UsageCurve({rows}:{rows:AdminAnalytics['daily']}){
 const width=900,height=260,pad=34,max=Math.max(1,...rows.map(row=>row.tokens));const points=rows.map((row,index)=>({x:pad+(width-pad*2)*(rows.length===1?.5:index/Math.max(1,rows.length-1)),y:height-pad-(height-pad*2)*row.tokens/max,row}))
 const path=points.map((point,index)=>`${index?'L':'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')
 return rows.length?<div className="developer-curve"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="每日 Token 用量曲线"><line x1={pad} y1={height-pad} x2={width-pad} y2={height-pad} className="developer-axis"/><path d={path} className="developer-line" fill="none"/>{points.map(point=><g key={point.row.date} className="developer-point"><circle cx={point.x} cy={point.y} r="5"/><title>{point.row.date} · {point.row.tokens.toLocaleString()} tokens · {point.row.model_calls} 次模型调用</title></g>)}</svg><div className="developer-axis-label"><span>{rows[0].date}</span><span>{rows.at(-1)?.date}</span></div></div>:<Empty description="该周期暂无模型调用"/>
}

export default function DeveloperAnalytics(){
 const[days,setDays]=useState(30);const[data,setData]=useState<AdminAnalytics>();const[loading,setLoading]=useState(true)
 useEffect(()=>{setLoading(true);api.adminAnalytics(days).then(setData).finally(()=>setLoading(false))},[days])
 const featureRows=useMemo(()=>data?.features??[],[data])
 return <div className="workspace-page developer-page">
  <div className="page-heading page-heading-rich"><Typography.Title level={2}>开发者数据</Typography.Title><Segmented value={days} onChange={value=>setDays(Number(value))} options={[{label:'7 天',value:7},{label:'30 天',value:30},{label:'90 天',value:90},{label:'全部',value:3650}]}/></div>
  <Spin spinning={loading}>{data&&<>
   <div className="developer-kpis"><Card><Statistic title="注册账号" value={data.totals.users} prefix={<TeamOutlined/>}/><small>{data.totals.active_users} 个账号在周期内有操作</small></Card><Card><Statistic title="应用 API 请求" value={data.totals.api_calls} prefix={<ApiOutlined/>}/><small>服务器真实接收并完成计数</small></Card><Card><Statistic title="模型调用" value={data.totals.model_calls} prefix={<ThunderboltOutlined/>}/><small>{compact(data.totals.tokens)} 个供应商回传 token</small></Card><Card><Statistic title="云剧库" value={data.totals.cloud_assets} prefix={<CloudServerOutlined/>}/><small>{bytes(data.totals.cloud_bytes)} · 硬链接不重复占盘</small></Card></div>
   <Card title="Token 用量趋势" className="developer-chart-card"><UsageCurve rows={data.daily}/></Card>
   <div className="developer-tables"><Card title="账号用量"><Table rowKey="user_id" size="small" dataSource={data.users} pagination={false} columns={[{title:'账号',dataIndex:'email',ellipsis:true},{title:'API',dataIndex:'api_calls',width:85},{title:'模型调用',dataIndex:'model_calls',width:95},{title:'输入 Token',dataIndex:'input_tokens',width:110,render:compact},{title:'输出 Token',dataIndex:'output_tokens',width:110,render:compact},{title:'失败',dataIndex:'failures',width:75,render:(value:number)=>value?<Tag color="red">{value}</Tag>:<Tag>0</Tag>}]} scroll={{x:760}}/></Card>
    <Card title="功能使用"><Table rowKey="feature" size="small" dataSource={featureRows} pagination={{pageSize:10}} columns={[{title:'功能',dataIndex:'feature',ellipsis:true},{title:'次数',dataIndex:'uses',width:75},{title:'使用率',dataIndex:'usage_rate',width:90,render:(value:number)=>`${value}%`},{title:'成功率',dataIndex:'success_rate',width:90,render:(value:number|null)=>value===null?'—':`${value}%`},{title:'缓存命中',dataIndex:'hit_rate',width:95,render:(value:number|null)=>value===null?'—':`${value}%`},{title:'Token',dataIndex:'tokens',width:90,render:compact}]} scroll={{x:680}}/></Card></div>
   <Card title="统计口径" className="developer-definitions"><div>{Object.entries(data.definitions).map(([name,value])=><p key={name}><b>{name}</b><span>{value}</span></p>)}</div></Card>
  </>}</Spin>
 </div>
}
