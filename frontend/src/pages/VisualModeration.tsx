import { useEffect,useState } from 'react'
import { Button,Card,Empty,message,Progress,Select,Space,Table,Tag,Typography } from 'antd'
import { SafetyCertificateOutlined } from '@ant-design/icons'
import { api,Clip,VisualReview } from '../api'

export default function VisualModeration({embedded=false}:{embedded?:boolean}){
 const[clips,setClips]=useState<Clip[]>([]);const[clipId,setClipId]=useState<number>();const[reviews,setReviews]=useState<VisualReview[]>([]);const[quota,setQuota]=useState({used:0,limit:200});const[busy,setBusy]=useState(false);const[msg,holder]=message.useMessage()
 const load=async()=>{const[c,r,q]=await Promise.all([api.clips(),api.visualReviews(),api.visualQuota()]);const completed=c.filter(x=>x.current_step==='completed');setClips(completed);setReviews(r);setQuota(q);setClipId(current=>current??completed[0]?.id)};useEffect(()=>{load().catch(e=>msg.error(e.message))},[])
 const scan=async()=>{if(!clipId)return;setBusy(true);try{const r=await api.scanVisual(clipId);msg.success(r.risk==='green'?'检测完成：自动放行':`${r.risk==='red'?'红色':'黄色'}风险：已进入人工复核`);await load()}catch(e){msg.error((e as Error).message)}finally{setBusy(false)}}
 const color:Record<string,string>={green:'green',yellow:'gold',red:'red'}
 const cols=[{title:'切片',dataIndex:'clip_id',render:(x:number)=>`#${x}`},{title:'风险',dataIndex:'risk',render:(x:string)=><Tag color={color[x]}>{x==='green'?'绿色':x==='yellow'?'黄色':'红色'}</Tag>},{title:'理由',render:(_:unknown,r:VisualReview)=>r.reasons.join('；')},{title:'检测来源',dataIndex:'provider'},{title:'状态',dataIndex:'status'},{title:'人工复核',render:(_:unknown,r:VisualReview)=><Space><Button disabled={r.status!=='review'} type="primary" onClick={()=>api.decideVisual(r.id,'approved').then(load)}>通过</Button><Button disabled={r.status!=='review'} danger onClick={()=>api.decideVisual(r.id,'blocked').then(load)}>拦截</Button></Space>}]
 return <div className={embedded?'factory-inner':'workspace-page'}>{holder}{!embedded&&<Typography.Title level={2}>视觉敏感检测与复核</Typography.Title>}
  <div className="module-toolbar"><b>画面敏感检测</b><Space wrap><Select aria-label="待检测切片" value={clipId} onChange={setClipId} style={{width:220}} options={clips.map(x=>({value:x.id,label:`切片 #${x.id}`}))}/><Button type="primary" icon={<SafetyCertificateOutlined/>} disabled={!clipId} loading={busy} onClick={scan}>检测视频抽帧</Button></Space></div>
  <Card title={`近 24 小时模型调用 ${quota.used}/${quota.limit}`}><Progress percent={quota.limit?Math.round(quota.used/quota.limit*100):0}/></Card>
  <Card className="table-card" title="人工复核队列"><Table rowKey="id" dataSource={reviews} columns={cols} locale={{emptyText:<Empty description="暂无待复核记录"/>}} scroll={{x:760}}/></Card>
 </div>
}
