import { useEffect, useState } from 'react'
import { Alert, Button, Card, Empty, message, Progress, Select, Space, Table, Tag, Typography } from 'antd'
import { ScissorOutlined } from '@ant-design/icons'
import { api, Clip, Drama } from '../api'

const stepLabel: Record<string, string> = {
  queued:'等待中',starting:'准备中',cutting:'切片',audio:'分离人声并替换 BGM',subtitles:'识别并烧录字幕',
  formatting:'竖屏规格化',preview:'生成六帧预览',completed:'已完成',failed:'失败',
}

export default function Production({embedded=false,initialDramaId}:{embedded?:boolean;initialDramaId?:number}) {
  const [dramas,setDramas]=useState<Drama[]>([])
  const [clips,setClips]=useState<Clip[]>([])
  const [dramaId,setDramaId]=useState<number|undefined>(initialDramaId)
  const [creating,setCreating]=useState(false)
  const [msg,context]=message.useMessage()

  const refresh=async()=>{try{setClips(await api.clips(dramaId))}catch(e){msg.error((e as Error).message)}}
  useEffect(()=>{api.list().then(data=>{setDramas(data);setDramaId(current=>initialDramaId??current??data[0]?.id)}).catch(e=>msg.error(e.message))},[initialDramaId])
  useEffect(()=>{if(initialDramaId)setDramaId(initialDramaId)},[initialDramaId])
  useEffect(()=>{void refresh();const timer=window.setInterval(()=>void refresh(),2000);return()=>window.clearInterval(timer)},[dramaId])

  const create=async()=>{if(!dramaId)return;setCreating(true);try{const data=await api.createClips(dramaId);msg.success(`${data.length} 条高能点已进入剪辑队列`);await refresh()}catch(e){msg.error((e as Error).message)}finally{setCreating(false)}}
  const review=async(id:number,status:'approved'|'blocked')=>{try{await api.reviewClip(id,status);msg.success(status==='approved'?'成品已通过':'成品已拦截');await refresh()}catch(e){msg.error((e as Error).message)}}
  const columns=[
    {title:'任务',dataIndex:'id',render:(id:number,row:Clip)=><Space direction="vertical" size={0}><b>#{id}</b><Typography.Text type="secondary">{row.source_eps[0]} · {row.source_start}s–{row.source_end}s</Typography.Text></Space>},
    {title:'进度',width:270,render:(_:unknown,row:Clip)=><Space direction="vertical" className="progress-cell"><span>{stepLabel[row.current_step]??row.current_step}</span><Progress percent={row.progress} status={row.current_step==='failed'?'exception':row.current_step==='completed'?'success':'active'}/></Space>},
    {title:'时长',dataIndex:'duration',render:(x:number)=>`${Number(x||0).toFixed(1)} 秒`},
    {title:'音频',render:(_:unknown,row:Clip)=>row.current_step==='queued'?'-':row.audio_replaced?<Tag color="green">BGM 已替换</Tag>:<Tag color="orange">保留原音频</Tag>},
    {title:'状态',render:(_:unknown,row:Clip)=><Space direction="vertical"><Tag color={row.current_step==='failed'?'red':row.current_step==='completed'?'green':'blue'}>{stepLabel[row.current_step]??row.current_step}</Tag>{row.error_message&&<Typography.Text type="danger">{row.error_message.slice(0,100)}</Typography.Text>}</Space>},
    {title:'产物',render:(_:unknown,row:Clip)=>row.current_step==='completed'?<Space><a href={`/api/clips/${row.id}/preview`} target="_blank">六帧预览</a><a href={`/api/clips/${row.id}/video`} target="_blank">查看视频</a></Space>:'-'},
    {title:'终审',render:(_:unknown,row:Clip)=><Space><Button size="small" type="primary" disabled={row.current_step!=='completed'} onClick={()=>review(row.id,'approved')}>通过</Button><Button size="small" danger disabled={row.current_step!=='completed'} onClick={()=>review(row.id,'blocked')}>拦截</Button></Space>},
  ]

  return <div className={embedded?'factory-inner':'workspace-page'}>{context}
    {!embedded&&<div className="page-heading"><Typography.Title level={2}>批量剪辑</Typography.Title></div>}
    <div className="module-toolbar"><b>批量剪辑队列</b><Space wrap><Select placeholder="选择剧目" value={dramaId} onChange={setDramaId} options={dramas.map(x=>({value:x.id,label:x.title}))} style={{width:220}}/><Button type="primary" icon={<ScissorOutlined/>} loading={creating} disabled={!dramaId} onClick={create}>按高能点批量剪辑</Button></Space></div>
    <Card className="table-card">{clips.length?<Table rowKey="id" dataSource={clips} columns={columns} pagination={false} scroll={{x:1050}} expandable={{expandedRowRender:row=><div className="review-panel"><div><b>命中词：</b>{row.hit_words.length?row.hit_words.map(x=><Tag color="red" key={x}>{x}</Tag>):'无'}</div>{row.error_message&&<Alert type="error" showIcon message="处理日志" description={<pre className="error-detail">{row.error_message}\n\n建议：{row.error_advice}</pre>}/>}<div className="subtitle-text">{row.subtitle_text||'暂无字幕'}</div></div>}}/>:<Empty description="当前剧目还没有剪辑任务；先在脚本拆解中采纳高能点"/>}</Card>
  </div>
}
