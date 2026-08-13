import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Avatar,
  Button,
  Card,
  Empty,
  Popover,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CalendarOutlined,
  ClockCircleOutlined,
  CommentOutlined,
  DownloadOutlined,
  ExportOutlined,
  EyeOutlined,
  LikeOutlined,
  ReloadOutlined,
  SyncOutlined,
  TranslationOutlined,
  UserOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, type Account, type AccountInsights, type AccountInsightPoint, type PlatformMedia, type SocialComment } from '../api'
import { PlatformBadge, PlatformLogo, PlatformOption } from '../components/PlatformBrand'
import { SmoothLineChart } from '../components/SmoothLineChart'

const fmt = (value:number|null|undefined) => value == null ? '—' : new Intl.NumberFormat('zh-CN').format(value)
const compact = (value:number|null|undefined) => value == null ? '—' : new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:1}).format(value)
const money = (value:number|null|undefined) => value == null ? '—' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(value)
const percent = (value:number|null|undefined) => value == null ? '—' : `${value.toFixed(2)}%`
const duration = (seconds:number|null|undefined) => {
  if (seconds == null) return '—'
  const hours=Math.floor(seconds/3600);const minutes=Math.floor((seconds%3600)/60)
  if(hours)return `${fmt(hours)} 小时 ${minutes} 分`
  if(minutes)return `${minutes} 分 ${seconds%60} 秒`
  return `${seconds} 秒`
}
const dateKey=(date:Date)=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`
const addDays=(date:Date,amount:number)=>{const next=new Date(date);next.setDate(next.getDate()+amount);return next}
const startOfWeek=(date:Date)=>{const next=new Date(date);const day=next.getDay();next.setDate(next.getDate()-(day===0?6:day-1));next.setHours(0,0,0,0);return next}
const startOfMonthGrid=(date:Date)=>{const first=new Date(date.getFullYear(),date.getMonth(),1);const day=first.getDay();return addDays(first,-(day===0?6:day-1))}
const validDate=(value:string|null|undefined)=>{
  if(!value)return null
  const date=new Date(value)
  return Number.isNaN(date.getTime())?null:date
}
const calendarDate=(item:PlatformMedia)=>validDate(item.calendar_at||item.scheduled_at||item.published_at)
const sentimentMeta:Record<string,[string,string]>={positive:['正面','green'],negative:['负面','red'],neutral:['中性','default'],unanalyzed:['待分析','orange']}

function InsightMetric({label,value,sub,muted=false}:{label:string;value:string;sub?:string;muted?:boolean}){
  return <div className="insight-metric"><span>{label}</span><strong className={muted?'metric-empty':''}>{value}</strong>{sub&&<small>{sub}</small>}</div>
}

const changeText=(value:number|null|undefined)=>value==null?'无可比数据':`${value>=0?'+':''}${value.toFixed(1)}% 环比`
const exportHref=(path:string)=>path

type TrendMetric='views'|'watch_time_seconds'|'estimated_revenue'|'subscribers_gained'
type InsightRange='all'|'7'|'28'|'90'
const trendMeta:Record<TrendMetric,{label:string;format:(value:number)=>string}> = {
  views:{label:'播放量',format:compact},
  watch_time_seconds:{label:'观看时长',format:value=>duration(value)},
  estimated_revenue:{label:'广告收入',format:value=>money(value)},
  subscribers_gained:{label:'新增订阅',format:fmt},
}

function TrendChart({series,metric}:{series:AccountInsightPoint[];metric:TrendMetric}){
  const availableSeries=series.filter(item=>item[metric]!=null)
  const longRange=availableSeries.length>1&&new Date(availableSeries.at(-1)!.date).getTime()-new Date(availableSeries[0].date).getTime()>180*86400000
  const points=availableSeries.map(item=>({
    label:item.date,
    axisLabel:longRange?item.date.slice(0,7):item.date.slice(5),
    value:Number(item[metric]),
    details:[
      {label:'播放量',value:fmt(item.views)},
      {label:'展现量',value:fmt(item.impressions)},
      {label:'点击率',value:percent(item.ctr)},
      {label:'观看时长',value:duration(item.watch_time_seconds)},
      {label:'平均观看',value:duration(item.average_view_duration_seconds)},
      {label:'广告收入',value:money(item.estimated_revenue)},
      {label:'新增订阅',value:fmt(item.subscribers_gained)},
    ].filter(detail=>detail.label!==trendMeta[metric].label&&detail.value!=='—'),
  }))
  return <div className="insight-chart-wrap"><SmoothLineChart points={points} seriesName={trendMeta[metric].label} valueFormat={trendMeta[metric].format} ariaLabel={`${trendMeta[metric].label}趋势图`} emptyText={`平台未返回${trendMeta[metric].label}数据`}/></div>
}

function ContentPerformance({items}:{items:PlatformMedia[]}){
  const rows=[...items].sort((a,b)=>String(a.published_at||'').localeCompare(String(b.published_at||''))).slice(-12)
  const points=rows.map((item,index)=>{
    const date=item.published_at?new Date(item.published_at):null
    return{
      label:item.title||`视频 ${index+1}`,
      axisLabel:date?`${date.getMonth()+1}-${String(date.getDate()).padStart(2,'0')}`:String(index+1),
      value:item.views,
      details:[
        {label:'发布时间',value:date?date.toLocaleString('zh-CN'):'未知'},
        {label:'点赞',value:fmt(item.likes)},
        {label:'评论',value:fmt(item.comments)},
        {label:'点击率',value:percent(item.ctr)},
        {label:'平均观看',value:duration(item.average_view_duration_seconds)},
        {label:'总观看时长',value:duration(item.watch_time_seconds)},
        {label:'广告收入',value:money(item.estimated_revenue)},
        {label:'RPM',value:money(item.rpm)},
        {label:'新增订阅',value:fmt(item.subscribers_gained)},
      ].filter(detail=>detail.value!=='—'),
    }
  })
  return <SmoothLineChart points={points} seriesName="播放量" valueFormat={compact} ariaLabel="视频播放表现曲线" emptyText="平台暂未返回视频"/>
}

function VideoPopover({item}:{item:PlatformMedia}){
  const displayTime=calendarDate(item)
  return <div className="video-hover-card">
    {item.thumbnail_url&&<img src={item.thumbnail_url} alt=""/>}
    <strong>{item.title||'未命名视频'}</strong>
    <span>{displayTime?displayTime.toLocaleString('zh-CN'):'发布时间未知'}</span>
    <div><span><EyeOutlined/> {fmt(item.views)}</span><span><LikeOutlined/> {fmt(item.likes)}</span><span><CommentOutlined/> {fmt(item.comments)}</span></div>
    <div><span>点击率 {percent(item.ctr)}</span><span>平均观看 {duration(item.average_view_duration_seconds)}</span><span>RPM {money(item.rpm)}</span></div>
  </div>
}

function VideoEvent({item,compactView=false}:{item:PlatformMedia;compactView?:boolean}){
  const displayTime=calendarDate(item)
  const event=<div className={`calendar-video ${compactView?'calendar-video-compact':''}`} onClick={()=>item.url&&window.open(item.url,'_blank','noopener,noreferrer')}>
    {item.thumbnail_url?<img src={item.thumbnail_url} alt=""/>:<span className="video-placeholder"><VideoCameraOutlined/></span>}
    <div><b>{item.title||'未命名视频'}</b>{!compactView&&<small>{displayTime?displayTime.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):''}</small>}</div>
  </div>
  return <Popover content={<VideoPopover item={item}/>} trigger="hover" mouseEnterDelay={.15}>{event}</Popover>
}

function WeekCalendar({cursor,items}:{cursor:Date;items:PlatformMedia[]}){
  const start=startOfWeek(cursor);const days=Array.from({length:7},(_,index)=>addDays(start,index));const hours=[0,4,8,12,16,20]
  return <div className="calendar-scroll"><div className="week-calendar">
    <div className="week-corner"><ClockCircleOutlined/></div>
    {days.map(day=><div className={`week-day-head ${dateKey(day)===dateKey(new Date())?'is-today':''}`} key={dateKey(day)}><span>{day.toLocaleDateString('zh-CN',{weekday:'short'})}</span><b>{day.getDate()}</b></div>)}
    <div className="week-time-axis">{hours.map(hour=><span key={hour} style={{top:`${hour/24*100}%`}}>{String(hour).padStart(2,'0')}:00</span>)}</div>
    {days.map(day=>{
      const dayItems=items.filter(item=>{const published=calendarDate(item);return published&&dateKey(published)===dateKey(day)})
      return <div className={`week-day-column ${dateKey(day)===dateKey(new Date())?'is-today':''}`} key={dateKey(day)}>
        {dayItems.map((item,index)=>{const published=calendarDate(item)!;const minutes=published.getHours()*60+published.getMinutes();return <div className="week-event-position" style={{top:`calc(${minutes/1440*100}% + ${index%3*5}px)`}} key={item.id}><VideoEvent item={item}/></div>})}
      </div>
    })}
  </div></div>
}

function MonthCalendar({cursor,items}:{cursor:Date;items:PlatformMedia[]}){
  const start=startOfMonthGrid(cursor);const days=Array.from({length:42},(_,index)=>addDays(start,index))
  return <div className="calendar-scroll"><div className="month-calendar">
    {['周一','周二','周三','周四','周五','周六','周日'].map(day=><div className="month-weekday" key={day}>{day}</div>)}
    {days.map(day=>{const dayItems=items.filter(item=>{const published=calendarDate(item);return published&&dateKey(published)===dateKey(day)});return <div className={`month-day ${day.getMonth()!==cursor.getMonth()?'is-outside':''} ${dateKey(day)===dateKey(new Date())?'is-today':''}`} key={dateKey(day)}><span className="month-date">{day.getDate()}</span><div className="month-events">{dayItems.slice(0,3).map(item=><VideoEvent key={item.id} item={item} compactView/>)}{dayItems.length>3&&<small>还有 {dayItems.length-3} 条</small>}</div></div>})}
  </div></div>
}

function CommentCard({item,account}:{item:SocialComment;account?:Account}){
  const sentiment=sentimentMeta[item.sentiment]||[item.sentiment,'default']
  return <article className="latest-comment-card">
    <div className="comment-card-avatar"><Avatar icon={<UserOutlined/>}/></div>
    <div className="comment-card-main">
      <div className="comment-card-meta"><strong>{item.author_name||'匿名用户'}</strong>{item.author_handle&&<span>{item.author_handle}</span>}<time>{item.published_at?new Date(item.published_at).toLocaleString('zh-CN'):'时间未知'}</time></div>
      <p className="comment-original">{item.text_original}</p>
      <div className={`comment-translation ${item.text_zh?'':'is-pending'}`}><TranslationOutlined/><span>{item.text_zh||(/\p{L}/u.test(item.text_original)?'暂无中文翻译':'仅表情，无需翻译')}</span></div>
      <div className="comment-card-footer">
        <Space size={7} wrap><PlatformBadge platform={item.platform}/>{account&&<span>{account.name}</span>}<Tag color={sentiment[1]}>{sentiment[0]}</Tag><span><LikeOutlined/> {fmt(item.like_count)}</span></Space>
        {item.video_url?<a href={item.video_url} target="_blank" rel="noreferrer"><VideoCameraOutlined/> {item.video_title||item.video_id||'来源视频'} <ExportOutlined/></a>:<span><VideoCameraOutlined/> {item.video_title||item.video_id||'来源视频未知'}</span>}
      </div>
    </div>
  </article>
}

export default function DashboardPage(){
  const [accounts,setAccounts]=useState<Account[]>([])
  const [comments,setComments]=useState<SocialComment[]>([])
  const [media,setMedia]=useState<PlatformMedia[]>([])
  const [calendarMedia,setCalendarMedia]=useState<PlatformMedia[]>([])
  const [insights,setInsights]=useState<AccountInsights>()
  const [selectedAccountId,setSelectedAccountId]=useState<number>()
  const [activeSection,setActiveSection]=useState<'accounts'|'publishing'|'fans'>('accounts')
  const [insightDays,setInsightDays]=useState<InsightRange>('all')
  const [contentType,setContentType]=useState<'all'|'videos'|'shorts'>('all')
  const [trendMetric,setTrendMetric]=useState<TrendMetric>('views')
  const [calendarView,setCalendarView]=useState<'week'|'month'>('week')
  const [calendarCursor,setCalendarCursor]=useState(new Date())
  const [commentSort,setCommentSort]=useState<'latest'|'video'|'user'>('latest')
  const [commentAccount,setCommentAccount]=useState<number|'all'>('all')
  const [loading,setLoading]=useState(false)
  const [mediaLoading,setMediaLoading]=useState(false)
  const [insightLoading,setInsightLoading]=useState(false)
  const [insightError,setInsightError]=useState('')
  const [commentWorking,setCommentWorking]=useState(false)
  const [mediaError,setMediaError]=useState('')
  const mediaCache=useRef(new Map<number,PlatformMedia[]>())
  const calendarCache=useRef(new Map<number,PlatformMedia[]>())
  const insightCache=useRef(new Map<string,AccountInsights>())
  const autoRefreshedAccounts=useRef(new Set<number>())
  const commentsLoaded=useRef(false)
  const mediaRequest=useRef(0)
  const calendarRequest=useRef(0)
  const insightRequest=useRef(0)
  const [msg,holder]=message.useMessage()
  const navigate=useNavigate()
  const selectedAccount=accounts.find(item=>item.id===selectedAccountId)

  const load=async(force=false)=>{
    setLoading(true)
    try{
      const accountRows=await api.accounts(force)
      setAccounts(accountRows)
      setSelectedAccountId(current=>current&&accountRows.some(item=>item.id===current)?current:accountRows[0]?.id)
    }catch(error){msg.error((error as Error).message)}finally{setLoading(false)}
  }
  const loadComments=async(force=false)=>{
    if(commentsLoaded.current&&!force)return
    try{setComments(await api.socialComments('',force));commentsLoaded.current=true}catch(error){msg.error((error as Error).message)}
  }
  const loadMedia=async(accountId:number,force=false)=>{
    const requestId=++mediaRequest.current
    const cached=mediaCache.current.get(accountId)
    if(cached&&!force){setMedia(cached);return}
    setMediaLoading(true);setMediaError('')
    try{const rows=await api.accountMedia(accountId,50,force);mediaCache.current.set(accountId,rows);if(requestId===mediaRequest.current)setMedia(rows)}catch(error){if(requestId===mediaRequest.current){setMedia([]);setMediaError((error as Error).message)}}finally{if(requestId===mediaRequest.current)setMediaLoading(false)}
  }
  const loadCalendar=async(accountId:number,force=false)=>{
    const requestId=++calendarRequest.current
    const cached=calendarCache.current.get(accountId)
    if(cached&&!force){setCalendarMedia(cached);return}
    setMediaLoading(true);setMediaError('')
    try{const rows=await api.accountCalendar(accountId,200,force);calendarCache.current.set(accountId,rows);if(requestId===calendarRequest.current)setCalendarMedia(rows)}catch(error){if(requestId===calendarRequest.current){setCalendarMedia([]);setMediaError((error as Error).message)}}finally{if(requestId===calendarRequest.current)setMediaLoading(false)}
  }
  const loadInsights=async(accountId:number,days:InsightRange=insightDays,type=contentType,force=false)=>{
    const requestId=++insightRequest.current
    const key=`${accountId}:${days}:${type}`;const cached=insightCache.current.get(key)
    if(cached&&!force){setInsights(cached);return}
    setInsightLoading(true);setInsightError('')
    try{const result=await api.accountInsights(accountId,days,type,force);insightCache.current.set(key,result);if(requestId===insightRequest.current)setInsights(result)}catch(error){if(requestId===insightRequest.current){setInsights(undefined);setInsightError((error as Error).message)}}finally{if(requestId===insightRequest.current)setInsightLoading(false)}
  }
  useEffect(()=>{void load()},[])
  useEffect(()=>{if(selectedAccount?.platform!=='youtube'&&contentType!=='all')setContentType('all')},[selectedAccount?.platform,contentType])
  useEffect(()=>{
    if(!selectedAccountId)return
    if(activeSection==='accounts'){
      const firstLoad=!autoRefreshedAccounts.current.has(selectedAccountId)
      if(firstLoad)autoRefreshedAccounts.current.add(selectedAccountId)
      void loadInsights(selectedAccountId,insightDays,contentType,firstLoad)
      void loadMedia(selectedAccountId,firstLoad)
    }
    if(activeSection==='publishing')void loadCalendar(selectedAccountId)
    if(activeSection==='fans')void loadComments()
  },[activeSection,selectedAccountId,insightDays,contentType])

  const visibleRange=useMemo(()=>{
    if(calendarView==='week'){const start=startOfWeek(calendarCursor);return{start,end:addDays(start,7)}}
    const start=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth(),1);return{start,end:new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()+1,1)}
  },[calendarCursor,calendarView])
  const visibleMedia=useMemo(()=>calendarMedia.filter(item=>{const published=calendarDate(item);return published&&published>=visibleRange.start&&published<visibleRange.end}).sort((a,b)=>(calendarDate(a)?.getTime()||0)-(calendarDate(b)?.getTime()||0)),[calendarMedia,visibleRange])
  const accountMedia=useMemo(()=>contentType==='all'?media:media.filter(item=>item.content_type===contentType),[media,contentType])
  const filteredComments=useMemo(()=>comments.filter(item=>commentAccount==='all'||item.account_id===commentAccount).sort((a,b)=>{
    if(commentSort==='video')return (a.video_title||a.video_id).localeCompare(b.video_title||b.video_id,'zh-CN')||new Date(b.published_at||0).getTime()-new Date(a.published_at||0).getTime()
    if(commentSort==='user')return (a.author_name||a.author_handle).localeCompare(b.author_name||b.author_handle,'zh-CN')||new Date(b.published_at||0).getTime()-new Date(a.published_at||0).getTime()
    return new Date(b.published_at||0).getTime()-new Date(a.published_at||0).getTime()
  }),[comments,commentAccount,commentSort])
  const commentGroups=useMemo(()=>{
    if(commentSort==='latest')return [{key:'latest',title:'最新评论',items:filteredComments}]
    const map=new Map<string,SocialComment[]>()
    filteredComments.forEach(item=>{const key=commentSort==='video'?(item.video_title||item.video_id||'未知视频'):(item.author_name||item.author_handle||'匿名用户');map.set(key,[...(map.get(key)||[]),item])})
    return Array.from(map.entries()).map(([key,items])=>({key,title:key,items}))
  },[filteredComments,commentSort])
  const syncComments=async()=>{setCommentWorking(true);try{const connected=accounts.filter(item=>item.status==='connected').map(item=>item.id);const result=await api.syncComments(connected,300);msg.success(`已同步并本地翻译 ${result.created+result.updated} 条评论`);setComments(await api.socialComments())}catch(error){msg.error((error as Error).message)}finally{setCommentWorking(false)}}
  const moveCalendar=(direction:number)=>setCalendarCursor(current=>calendarView==='week'?addDays(current,direction*7):new Date(current.getFullYear(),current.getMonth()+direction,1))
  const insightTotals=insights?.totals
  const netSubscribers=insightTotals?.subscribers_gained==null?null:insightTotals.subscribers_gained-(insightTotals.subscribers_lost||0)
  const refreshSelected=()=>{if(!selectedAccountId)return;void loadInsights(selectedAccountId,insightDays,contentType,true);void loadMedia(selectedAccountId,true)}
  const accountExport=selectedAccountId?exportHref(`/api/publish/accounts/${selectedAccountId}/insights.csv?days=${insightDays}&content_type=${contentType}`):undefined
  const calendarExport=selectedAccountId?exportHref(`/api/publish/accounts/${selectedAccountId}/calendar.csv?start=${dateKey(visibleRange.start)}&end=${dateKey(addDays(visibleRange.end,-1))}`):undefined

  return <div className="workspace-page overview-page">{holder}
    <div className="page-heading overview-page-heading"><Typography.Title level={2}>账号总览</Typography.Title><Button icon={<ReloadOutlined/>} loading={loading||insightLoading} onClick={()=>{void load(true);refreshSelected()}}>刷新</Button></div>
    <Segmented block className="overview-pager" value={activeSection} onChange={value=>setActiveSection(value as typeof activeSection)} options={[{value:'accounts',label:'账号数据'},{value:'publishing',label:'发布日历'},{value:'fans',label:'粉丝评论'}]}/>

    {activeSection==='accounts'&&<section className="overview-section overview-accounts-section">
      <div className="account-data-toolbar">
        <Select className="account-filter" value={selectedAccountId} placeholder="选择账号" onChange={setSelectedAccountId} options={accounts.map(item=>({value:item.id,label:<PlatformOption platform={item.platform} label={item.name}/>}))}/>
        <Segmented value={insightDays} onChange={value=>setInsightDays(value as InsightRange)} options={[{value:'all',label:'全部'},{value:'7',label:'7天'},{value:'28',label:'28天'},{value:'90',label:'90天'}]}/>
        {selectedAccount?.platform==='youtube'&&<Segmented value={contentType} onChange={value=>setContentType(value as typeof contentType)} options={[{value:'all',label:'全部内容'},{value:'videos',label:'长视频'},{value:'shorts',label:'Shorts'}]}/>}
        <Button icon={<ReloadOutlined/>} loading={insightLoading||mediaLoading} disabled={!selectedAccountId} onClick={refreshSelected}>刷新数据</Button>
        <Button icon={<DownloadOutlined/>} href={accountExport} disabled={!accountExport}>导出数据表</Button>
        <Button type="link" onClick={()=>navigate('/management')}>管理账号 <ArrowRightOutlined/></Button>
      </div>
      {!accounts.length&&<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未连接账号"><Button type="primary" onClick={()=>navigate('/management')}>连接账号</Button></Empty>}
      {selectedAccount&&<Spin spinning={insightLoading}>
        <Card className="account-insight-hero">
          <div className="account-insight-head">
            <Avatar size={58} src={selectedAccount.avatar_url} icon={<PlatformLogo platform={selectedAccount.platform} size={28}/>}/>
            <div className="account-insight-identity">
              <div className="account-insight-title"><Typography.Title level={3}>{selectedAccount.name}</Typography.Title><PlatformLogo platform={selectedAccount.platform} size={20}/></div>
              {insights&&<Space size={6} wrap><Tag>{insights.range.start} — {insights.range.end}</Tag>{insights.unavailable.length>0&&<Popover title="平台数据权限" content={<ul className="data-availability-list">{insights.unavailable.map(item=><li key={item}>{item}</li>)}</ul>}><Tag color="gold">部分指标不可用</Tag></Popover>}</Space>}
            </div>
            {selectedAccount.profile_url&&<Button href={selectedAccount.profile_url} target="_blank" icon={<ExportOutlined/>}>打开主页</Button>}
          </div>
          {insightError?<div className="inline-error">{insightError}</div>:<div className="insight-metric-grid">
            <InsightMetric label={insightDays==='all'?'全部播放':`周期播放`} value={compact(insightTotals?.views)} sub={insightDays==='all'?(insightTotals?.channel_views!=null?`频道累计 ${fmt(insightTotals.channel_views)}`:undefined):changeText(insights?.changes.views)} muted={insightTotals?.views==null}/>
            <InsightMetric label="缩略图点击率" value={percent(insightTotals?.ctr)} sub={insightTotals?.impressions==null?(insightDays==='all'?undefined:changeText(insights?.changes.ctr)):`${fmt(insightTotals.impressions)} 次曝光${insightDays==='all'?'':` · ${changeText(insights?.changes.ctr)}`}`} muted={insightTotals?.ctr==null}/>
            <InsightMetric label="观看时长" value={duration(insightTotals?.watch_time_seconds)} sub={insightDays==='all'?(insightTotals?.average_view_duration_seconds!=null?`平均 ${duration(Math.round(insightTotals.average_view_duration_seconds))}`:undefined):`平均 ${duration(Math.round(insightTotals?.average_view_duration_seconds||0))} · ${changeText(insights?.changes.watch_time_seconds)}`} muted={insightTotals?.watch_time_seconds==null}/>
            <InsightMetric label="广告收入" value={money(insightTotals?.estimated_revenue)} sub={insightDays==='all'?'USD':changeText(insights?.changes.estimated_revenue)} muted={insightTotals?.estimated_revenue==null}/>
            <InsightMetric label="RPM" value={money(insightTotals?.rpm)} sub={insightDays==='all'?'每千次播放':changeText(insights?.changes.rpm)} muted={insightTotals?.rpm==null}/>
            <InsightMetric label="当前订阅数" value={fmt(insightTotals?.followers??selectedAccount.follower_count)} sub={netSubscribers==null?undefined:`周期净增 ${netSubscribers>=0?'+':''}${fmt(netSubscribers)}${insightDays==='all'?'':` · ${changeText(insights?.changes.net_subscribers)}`}`}/>
            <InsightMetric label="公开视频" value={fmt(insightTotals?.video_count)} muted={insightTotals?.video_count==null}/>
          </div>}
        </Card>

        {insights&&<>
          <Card className="insight-chart-card" title="账号趋势" extra={<Segmented size="small" value={trendMetric} onChange={value=>setTrendMetric(value as TrendMetric)} options={(Object.keys(trendMeta) as TrendMetric[]).map(value=>({value,label:trendMeta[value].label}))}/>}>
            <TrendChart series={insights.series} metric={trendMetric}/>
          </Card>
          <Card className="content-performance-card" title="视频播放表现" extra={<span className="cell-sub">{accountMedia.length} 条视频</span>}><ContentPerformance items={accountMedia}/></Card>
        </>}

        <Card className="table-card video-data-card account-media-table" title="最近视频详细数据" styles={{body:{padding:0}}}>
          <Table loading={mediaLoading} rowKey="id" dataSource={accountMedia} pagination={{pageSize:8,hideOnSinglePage:true}} scroll={{x:1320}} locale={{emptyText:<Empty description="平台暂未返回该类型视频"/>}} onRow={item=>({onClick:()=>item.url&&window.open(item.url,'_blank','noopener,noreferrer')})} columns={[
            {title:'视频',dataIndex:'title',width:320,render:(title:string,item:PlatformMedia)=><div className="video-table-title">{item.thumbnail_url?<img src={item.thumbnail_url} alt=""/>:<span><VideoCameraOutlined/></span>}<b>{title||'未命名视频'}</b></div>},
            {title:'发布时间',dataIndex:'published_at',width:170,render:(value:string|null)=>value?new Date(value).toLocaleString('zh-CN'):'—'},
            {title:'播放量',dataIndex:'views',width:100,render:fmt},{title:'点赞',dataIndex:'likes',width:90,render:fmt},{title:'评论',dataIndex:'comments',width:90,render:fmt},
            {title:'点击率',dataIndex:'ctr',width:100,render:percent},{title:'平均观看时长',dataIndex:'average_view_duration_seconds',width:140,render:duration},{title:'总观看时长',dataIndex:'watch_time_seconds',width:140,render:duration},
            {title:'广告收入',dataIndex:'estimated_revenue',width:110,render:money},{title:'RPM',dataIndex:'rpm',width:100,render:money},{title:'新增订阅',dataIndex:'subscribers_gained',width:100,render:fmt},
          ]}/>
        </Card>
      </Spin>}
    </section>}

    {activeSection==='publishing'&&<section className="overview-section publishing-calendar-section">
      <div className="calendar-toolbar">
        <Select className="account-filter" value={selectedAccountId} placeholder="选择账号" onChange={setSelectedAccountId} options={accounts.map(item=>({value:item.id,label:<PlatformOption platform={item.platform} label={item.name}/>}))}/>
        <div className="calendar-navigation"><Button icon={<ArrowLeftOutlined/>} onClick={()=>moveCalendar(-1)}/><Button onClick={()=>setCalendarCursor(new Date())}>今天</Button><Button icon={<ArrowRightOutlined/>} onClick={()=>moveCalendar(1)}/><strong>{calendarView==='week'?`${startOfWeek(calendarCursor).toLocaleDateString('zh-CN',{month:'long',day:'numeric'})} — ${addDays(startOfWeek(calendarCursor),6).toLocaleDateString('zh-CN',{month:'long',day:'numeric'})}`:`${calendarCursor.getFullYear()} 年 ${calendarCursor.getMonth()+1} 月`}</strong></div>
        <Segmented value={calendarView} onChange={value=>setCalendarView(value as typeof calendarView)} options={[{value:'week',label:'周'},{value:'month',label:'月'}]}/>
        <Button icon={<DownloadOutlined/>} href={calendarExport} disabled={!calendarExport}>导出排剧表</Button>
        <Button icon={<ReloadOutlined/>} loading={mediaLoading} disabled={!selectedAccountId} onClick={()=>selectedAccountId&&loadCalendar(selectedAccountId,true)}>刷新内容</Button>
      </div>
      <Spin spinning={mediaLoading}>
        <Card className="calendar-card" styles={{body:{padding:0}}}>{calendarView==='week'?<WeekCalendar cursor={calendarCursor} items={calendarMedia}/>:<MonthCalendar cursor={calendarCursor} items={calendarMedia}/>}</Card>
        {!selectedAccountId&&<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择账号查看发布日历"/>}
        {selectedAccountId&&mediaError&&<div className="inline-error">{mediaError}</div>}
      </Spin>
      <Card className="table-card video-data-card" title={<><CalendarOutlined/> 本期视频数据</>} styles={{body:{padding:0}}}>
        <Table rowKey="id" dataSource={visibleMedia} pagination={{pageSize:10,hideOnSinglePage:true}} scroll={{x:1180}} locale={{emptyText:<Empty description="当前周期没有已发布视频"/>}} onRow={item=>({onClick:()=>item.url&&window.open(item.url,'_blank','noopener,noreferrer')})} columns={[
          {title:'视频',dataIndex:'title',width:300,render:(title:string,item:PlatformMedia)=><div className="video-table-title">{item.thumbnail_url?<img src={item.thumbnail_url} alt=""/>:<span><VideoCameraOutlined/></span>}<b>{title||'未命名视频'}</b></div>},
          {title:'发布时间',width:170,render:(_:unknown,item:PlatformMedia)=>calendarDate(item)?.toLocaleString('zh-CN')||'—'},
          {title:'播放量',dataIndex:'views',width:100,render:fmt},{title:'互动',width:120,render:(_:unknown,item:PlatformMedia)=>`${fmt(item.likes)} / ${fmt(item.comments)}`},
          {title:'点击率',dataIndex:'ctr',width:100,render:percent},{title:'平均观看时长',dataIndex:'average_view_duration_seconds',width:140,render:duration},{title:'总观看时长',dataIndex:'watch_time_seconds',width:140,render:duration},
          {title:'广告收入',dataIndex:'estimated_revenue',width:110,render:money},{title:'RPM',dataIndex:'rpm',width:100,render:money},{title:'新增订阅',dataIndex:'subscribers_gained',width:100,render:fmt},
        ]}/>
      </Card>
    </section>}

    {activeSection==='fans'&&<section className="overview-section comments-overview-section">
      <div className="comments-toolbar">
        <Select value={commentAccount} onChange={setCommentAccount} options={[{value:'all',label:'全部账号'},...accounts.map(item=>({value:item.id,label:<PlatformOption platform={item.platform} label={item.name}/>}))]}/>
        <Segmented value={commentSort} onChange={value=>setCommentSort(value as typeof commentSort)} options={[{value:'latest',label:'最新'},{value:'video',label:'按视频'},{value:'user',label:'按用户'}]}/>
        <span className="comment-count">{filteredComments.length} 条评论</span>
        <Space wrap><Button type="primary" icon={<SyncOutlined/>} loading={commentWorking} onClick={syncComments}>同步最新评论</Button><Button icon={<ReloadOutlined/>} onClick={()=>void loadComments(true)}>刷新</Button></Space>
      </div>
      {filteredComments.length?<div className="comment-groups">{commentGroups.map(group=><section className="comment-group" key={group.key}>{commentSort!=='latest'&&<div className="comment-group-title"><strong>{group.title}</strong><span>{group.items.length}</span></div>}{group.items.map(item=><CommentCard key={item.id} item={item} account={accounts.find(account=>account.id===item.account_id)}/>)}</section>)}</div>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无评论"><Button type="primary" icon={<SyncOutlined/>} onClick={syncComments}>同步最新评论</Button></Empty>}
    </section>}
  </div>
}
