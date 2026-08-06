import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Collapse, Empty, message, Select, Space, Statistic, Table, Tabs, Tag, Typography } from 'antd'
import { FileSearchOutlined, FireOutlined, ReloadOutlined, SafetyCertificateOutlined, ScissorOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { api, Drama, FactoryAnalysis, ScriptSegment } from '../api'
import Production from './Production'
import VisualModeration from './VisualModeration'

const clock=(seconds:number)=>{const value=Math.max(0,Math.round(seconds));return `${String(Math.floor(value/60)).padStart(2,'0')}:${String(value%60).padStart(2,'0')}`}

export default function ContentFactory(){
  const[params]=useSearchParams()
  const[dramas,setDramas]=useState<Drama[]>([])
  const[dramaId,setDramaId]=useState<number>()
  const[analysis,setAnalysis]=useState<FactoryAnalysis>()
  const[busy,setBusy]=useState(false)
  const[tab,setTab]=useState('script')
  const[msg,holder]=message.useMessage()
  const drama=dramas.find(x=>x.id===dramaId)

  useEffect(()=>{api.list().then(items=>{setDramas(items);const requested=Number(params.get('drama'));setDramaId(items.some(x=>x.id===requested)?requested:items[0]?.id)}).catch(e=>msg.error(e.message))},[])
  useEffect(()=>{if(!dramaId){setAnalysis(undefined);return}api.factoryAnalysis(dramaId).then(setAnalysis).catch(e=>msg.error(e.message))},[dramaId])

  const analyze=async()=>{if(!dramaId)return;setBusy(true);try{const result=await api.analyzeFactory(dramaId);setAnalysis(result);msg.success(`脚本拆解完成：${result.segment_count} 个时间轴片段`)}catch(e){msg.error((e as Error).message)}finally{setBusy(false)}}
  const adopt=async(episode:string,segment:ScriptSegment)=>{if(!drama)return;const duplicate=drama.highlights.some(x=>x.episode===episode&&Math.abs(x.start-segment.start)<.1);if(duplicate)return msg.info('这个高能点已经采纳');try{const updated=await api.highlights(drama.id,[...drama.highlights,{episode,start:segment.start,end:segment.end,note:`脚本高能点：${segment.energy_reasons.join('；')||segment.text.slice(0,40)}`}]);setDramas(items=>items.map(x=>x.id===updated.id?updated:x));msg.success('已采纳到剪辑高能点')}catch(e){msg.error((e as Error).message)}}

  const highEnergy=useMemo(()=>analysis?.episodes.flatMap(ep=>ep.high_energy.map(row=>({episode:ep.episode,...row})))??[],[analysis])
  const sensitive=useMemo(()=>analysis?.episodes.flatMap(ep=>ep.sensitive.map(row=>({episode:ep.episode,...row})))??[],[analysis])
  const segmentColumns=[
    {title:'时间轴',width:120,render:(_:unknown,row:ScriptSegment)=>`${clock(row.start)}–${clock(row.end)}`},
    {title:'详细脚本',dataIndex:'text'},
    {title:'高能',width:100,render:(_:unknown,row:ScriptSegment)=>row.high_energy?<Tag color="orange">{row.energy_score.toFixed(1)}</Tag>:'-'},
    {title:'敏感内容',width:190,render:(_:unknown,row:ScriptSegment)=>Object.entries(row.sensitive).length?Object.entries(row.sensitive).map(([kind,words])=><Tag color="red" key={kind}>{kind}：{words.join('、')}</Tag>):'-'},
  ]
  const analysisReady=analysis?.status==='completed'

  return <div className="workspace-page factory-page">{holder}
    <div className="page-heading page-heading-rich"><Typography.Title level={2}>内容工厂</Typography.Title><Space wrap><Select placeholder="选择本地剧目" value={dramaId} onChange={setDramaId} options={dramas.map(x=>({value:x.id,label:x.title}))} style={{width:240}}/><Button icon={<ReloadOutlined/>} onClick={()=>dramaId&&api.factoryAnalysis(dramaId).then(setAnalysis)}>刷新</Button><Button type="primary" icon={<FileSearchOutlined/>} loading={busy} disabled={!dramaId} onClick={analyze}>{analysisReady?'重新拆解脚本':'拆解整部剧'}</Button></Space></div>
    <Tabs className="module-tabs" activeKey={tab} onChange={setTab} items={[
      {key:'script',label:<span><FileSearchOutlined/>脚本与内容识别</span>,children:<div className="factory-inner">
        {!drama?<Card><Empty description="请先到本地剧库导入待运营剧目"/></Card>:!analysisReady?<Card className="factory-empty"><Empty description="尚未拆解这部剧；点击右上角“拆解整部剧”开始真实本地分析"/></Card>:<>
          <div className="summary-strip factory-summary"><Statistic title="剧集" value={analysis.episode_count}/><Statistic title="总时长" value={clock(analysis.total_duration)}/><Statistic title="脚本片段" value={analysis.segment_count}/><Statistic title="高能点" value={analysis.high_energy_count} valueStyle={{color:'#d97706'}}/><Statistic title="敏感片段" value={analysis.sensitive_count} valueStyle={{color:analysis.sensitive_count?'#c2413b':undefined}}/></div>
          <Card title="逐集详细脚本" extra={<Typography.Text type="secondary">生成于 {analysis.generated_at?new Date(analysis.generated_at).toLocaleString():'-'}</Typography.Text>}><Collapse items={analysis.episodes.map(ep=>({key:ep.episode,label:<Space><b>{ep.episode}</b><Tag>{clock(ep.duration)}</Tag><span>{ep.segment_count} 段</span>{ep.high_energy.length>0&&<Tag color="orange">{ep.high_energy.length} 个高能点</Tag>}{ep.sensitive.length>0&&<Tag color="red">{ep.sensitive.length} 个敏感段</Tag>}</Space>,children:<Table size="small" rowKey={row=>`${ep.episode}-${row.start}`} dataSource={ep.segments} columns={segmentColumns} pagination={false} scroll={{x:760}}/>}))}/></Card>
          <div className="factory-review-grid"><Card title={<><FireOutlined/> 高能点候选</>} extra={<Tag color="orange">人工采纳后才能剪辑</Tag>}><Table size="small" rowKey={row=>`${row.episode}-${row.start}`} dataSource={highEnergy} pagination={false} locale={{emptyText:'没有检测到真实高能信号'}} columns={[{title:'剧集',dataIndex:'episode',width:100},{title:'时间',render:(_,row)=>`${clock(row.start)}–${clock(row.end)}`,width:115},{title:'脚本',dataIndex:'text',ellipsis:true},{title:'依据',render:(_,row)=>row.energy_reasons.join('；')},{title:'',render:(_,row)=><Button size="small" type="primary" onClick={()=>adopt(row.episode,row)}>采纳</Button>}]} scroll={{x:780}}/></Card>
          <Card title={<><SafetyCertificateOutlined/> 敏感情节</>}><Table size="small" rowKey={row=>`${row.episode}-${row.start}`} dataSource={sensitive} pagination={false} locale={{emptyText:'脚本文本未命中色情或暴力敏感词'}} columns={[{title:'剧集',dataIndex:'episode',width:90},{title:'时间',render:(_,row)=>`${clock(row.start)}–${clock(row.end)}`,width:110},{title:'脚本',dataIndex:'text',ellipsis:true},{title:'风险',render:(_,row)=>Object.entries(row.sensitive).map(([kind,words])=><Tag color="red" key={kind}>{kind} · {words.join('、')}</Tag>)}]} scroll={{x:650}}/></Card></div>
        </>}
      </div>},
      {key:'clips',label:<span><ScissorOutlined/>批量剪辑与成品</span>,children:<Production embedded initialDramaId={dramaId}/>},
      {key:'safety',label:<span><SafetyCertificateOutlined/>敏感画面终审</span>,children:<VisualModeration embedded/>},
    ]}/>
  </div>
}
