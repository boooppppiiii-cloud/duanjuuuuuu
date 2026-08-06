import { useEffect,useMemo,useState } from 'react'
import { Alert,Button,Card,Collapse,Empty,message,Modal,Progress,Segmented,Select,Space,Statistic,Table,Tag,Typography,Upload } from 'antd'
import { EyeOutlined,FileSearchOutlined,FireOutlined,FolderOpenOutlined,ReloadOutlined,SafetyCertificateOutlined,UploadOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { api,Clip,Drama,FactoryAnalysis,ScriptSegment,VisualReview } from '../api'
import Production from './Production'

const clock=(seconds:number)=>{const value=Math.max(0,Math.round(seconds));return `${String(Math.floor(value/60)).padStart(2,'0')}:${String(value%60).padStart(2,'0')}`}
const imageExtensions=new Set(['jpg','jpeg','png','webp'])

function FinalReview({dramaId,onSaved}:{dramaId?:number;onSaved:()=>void}){
  const[clips,setClips]=useState<Clip[]>([])
  const[reviews,setReviews]=useState<VisualReview[]>([])
  const[busy,setBusy]=useState<number|null>(null)
  const[msg,holder]=message.useMessage()
  const load=async()=>{if(!dramaId){setClips([]);setReviews([]);return}const[c,r]=await Promise.all([api.clips(dramaId),api.visualReviews()]);setClips(c.filter(x=>x.current_step==='completed'));setReviews(r)}
  useEffect(()=>{void load();const timer=window.setInterval(()=>void load(),2500);return()=>window.clearInterval(timer)},[dramaId])
  const inspect=async(clipId:number)=>{setBusy(clipId);try{await api.scanVisual(clipId);msg.success('敏感画面检测完成');await load()}catch(e){msg.error((e as Error).message)}finally{setBusy(null)}}
  const decide=async(clipId:number,status:'approved'|'blocked')=>{setBusy(clipId);try{await api.reviewClip(clipId,status);msg.success(status==='approved'?'已通过终审并保存到剧库“已生成”':'已拦截该成品');await load();onSaved()}catch(e){msg.error((e as Error).message)}finally{setBusy(null)}}
  const latest=(clipId:number)=>reviews.find(x=>x.clip_id===clipId)
  return <div className="factory-inner">{holder}<div className="module-toolbar"><b>成品终审</b><Button icon={<ReloadOutlined/>} onClick={()=>load()}>刷新</Button></div>
    <Card className="table-card">{clips.length?<Table rowKey="id" dataSource={clips} pagination={false} scroll={{x:900}} columns={[
      {title:'成品',render:(_,row)=><Space direction="vertical" size={0}><b>成品 #{row.id}</b><Typography.Text type="secondary">{row.source_eps[0]} · {clock(row.source_start)}–{clock(row.source_end)}</Typography.Text></Space>},
      {title:'时长',width:90,render:(_,row)=>`${row.duration.toFixed(1)} 秒`},
      {title:'文字风险',render:(_,row)=>row.hit_words.length?row.hit_words.map(x=><Tag color="red" key={x}>{x}</Tag>):<Tag color="green">未命中</Tag>},
      {title:'画面检测',width:150,render:(_,row)=>{const item=latest(row.id);return item?<Tag color={item.risk==='green'?'green':item.risk==='red'?'red':'orange'}>{item.risk==='green'?'低风险':item.risk==='red'?'高风险':'需复核'}</Tag>:<Button size="small" loading={busy===row.id} icon={<EyeOutlined/>} onClick={()=>inspect(row.id)}>检测</Button>}},
      {title:'预览',width:150,render:(_,row)=><Space><a href={`/api/clips/${row.id}/preview`} target="_blank">六帧</a><a href={`/api/clips/${row.id}/video`} target="_blank">视频</a></Space>},
      {title:'终审',width:230,render:(_,row)=><Space><Button type="primary" loading={busy===row.id} disabled={row.status==='approved'} onClick={()=>decide(row.id,'approved')}>{row.status==='approved'?'已保存':'通过并保存'}</Button><Button danger disabled={row.status==='blocked'} onClick={()=>decide(row.id,'blocked')}>拦截</Button></Space>},
    ]}/>:<Empty description="批量剪辑完成后，成品会进入这里"/>}</Card>
  </div>
}

export default function ContentFactory(){
  const[params]=useSearchParams()
  const[dramas,setDramas]=useState<Drama[]>([])
  const[dramaId,setDramaId]=useState<number>()
  const[analysis,setAnalysis]=useState<FactoryAnalysis>()
  const[busy,setBusy]=useState(false)
  const[tab,setTab]=useState<'script'|'clips'|'safety'>('script')
  const[uploadOpen,setUploadOpen]=useState(false)
  const[sourceFiles,setSourceFiles]=useState<File[]>([])
  const[uploadProgress,setUploadProgress]=useState<Record<string,number>>({})
  const[msg,holder]=message.useMessage()
  const drama=dramas.find(x=>x.id===dramaId)

  const reloadDramas=async(preferred=dramaId)=>{const items=await api.list();setDramas(items);const requested=Number(params.get('drama'));setDramaId(items.some(x=>x.id===preferred)?preferred:items.some(x=>x.id===requested)?requested:items[0]?.id)}
  useEffect(()=>{reloadDramas(undefined).catch(e=>msg.error(e.message))},[])
  useEffect(()=>{if(!dramaId){setAnalysis(undefined);return}api.factoryAnalysis(dramaId).then(setAnalysis).catch(e=>msg.error(e.message))},[dramaId])

  const analyze=async()=>{if(!dramaId)return;setBusy(true);try{const result=await api.analyzeFactory(dramaId);setAnalysis(result);msg.success(`脚本拆解完成，共 ${result.segment_count} 个时间轴片段`)}catch(e){msg.error((e as Error).message)}finally{setBusy(false)}}
  const adopt=async(episode:string,segment:ScriptSegment)=>{if(!drama)return;const duplicate=drama.highlights.some(x=>x.episode===episode&&Math.abs(x.start-segment.start)<.1);if(duplicate)return msg.info('这个高能点已经采纳');try{const updated=await api.highlights(drama.id,[...drama.highlights,{episode,start:segment.start,end:segment.end,note:`脚本高能点：${segment.energy_reasons.join('；')||segment.text.slice(0,40)}`}]);setDramas(items=>items.map(x=>x.id===updated.id?updated:x));msg.success('已采纳到剪辑高能点')}catch(e){msg.error((e as Error).message)}}
  const uploadSources=async()=>{if(!drama||!sourceFiles.length)return;setBusy(true);try{
    const ordered=[...sourceFiles].sort((a,b)=>imageExtensions.has(a.name.split('.').pop()?.toLowerCase()||'')?1:-1)
    for(const file of ordered){const ext=file.name.split('.').pop()?.toLowerCase()||'';const destination=imageExtensions.has(ext)?'stills':'episodes';await api.uploadVideo(drama.title,'内容工厂本地导入',file,value=>setUploadProgress(old=>({...old,[file.name]:value})),destination)}
    msg.success(`已导入 ${sourceFiles.length} 个本地文件`);setUploadOpen(false);setSourceFiles([]);setUploadProgress({});await reloadDramas(drama.id)
  }catch(e){msg.error((e as Error).message)}finally{setBusy(false)}}

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
    <div className="page-heading page-heading-rich"><Typography.Title level={2}>内容工厂</Typography.Title><Space wrap><Select placeholder="选择剧目任务" value={dramaId} onChange={setDramaId} options={dramas.map(x=>({value:x.id,label:x.title}))} style={{width:240}}/><Button icon={<FolderOpenOutlined/>} disabled={!drama} onClick={()=>setUploadOpen(true)}>导入原片文件夹</Button><Button type="primary" icon={<FileSearchOutlined/>} loading={busy} disabled={!drama?.episode_count} onClick={analyze}>{analysisReady?'重新拆解脚本':'拆解整部剧'}</Button></Space></div>
    {drama&&<div className="factory-task-strip"><b>{drama.title}</b><Tag>{drama.language}</Tag><span>原片 {drama.episode_count}/{drama.total_episode_count}</span><span>推广 {drama.promotion_episode_count} 集</span><span>已生成 {drama.generated_files.length}</span></div>}
    <Segmented block className="overview-pager factory-pager" value={tab} onChange={value=>setTab(value as typeof tab)} options={[{value:'script',label:'1 脚本识别'},{value:'clips',label:'2 批量剪辑'},{value:'safety',label:'3 成品终审'}]}/>
    {tab==='script'&&<div className="factory-inner">
      {!drama?<Card><Empty description="请先到剧库新建剧目任务"><Button href="/dramas" type="primary">前往剧库</Button></Empty></Card>:!drama.episode_count?<Card className="factory-empty"><Empty description="尚未导入原片"><Button type="primary" icon={<UploadOutlined/>} onClick={()=>setUploadOpen(true)}>选择本地文件夹</Button></Empty></Card>:!analysisReady?<Card className="factory-empty"><Empty description="点击右上角“拆解整部剧”开始识别脚本"/></Card>:<>
        <div className="summary-strip factory-summary"><Statistic title="已上传" value={analysis.episode_count} suffix="集"/><Statistic title="总时长" value={clock(analysis.total_duration)}/><Statistic title="脚本片段" value={analysis.segment_count}/><Statistic title="高能点" value={analysis.high_energy_count} valueStyle={{color:'#d97706'}}/><Statistic title="敏感片段" value={analysis.sensitive_count} valueStyle={{color:analysis.sensitive_count?'#c2413b':undefined}}/></div>
        <Card title="逐集详细脚本"><Collapse items={analysis.episodes.map(ep=>({key:ep.episode,label:<Space><b>{ep.episode}</b><Tag>{clock(ep.duration)}</Tag><span>{ep.segment_count} 段</span>{ep.high_energy.length>0&&<Tag color="orange">{ep.high_energy.length} 个高能点</Tag>}{ep.sensitive.length>0&&<Tag color="red">{ep.sensitive.length} 个敏感段</Tag>}</Space>,children:<Table size="small" rowKey={row=>`${ep.episode}-${row.start}`} dataSource={ep.segments} columns={segmentColumns} pagination={false} scroll={{x:760}}/>}))}/></Card>
        <div className="factory-review-grid"><Card title={<><FireOutlined/> 高能点候选</>}><Table size="small" rowKey={row=>`${row.episode}-${row.start}`} dataSource={highEnergy} pagination={false} locale={{emptyText:'没有检测到高能信号'}} columns={[{title:'剧集',dataIndex:'episode',width:100},{title:'时间',render:(_,row)=>`${clock(row.start)}–${clock(row.end)}`,width:115},{title:'脚本',dataIndex:'text',ellipsis:true},{title:'依据',render:(_,row)=>row.energy_reasons.join('；')},{title:'',render:(_,row)=><Button size="small" type="primary" onClick={()=>adopt(row.episode,row)}>采纳</Button>}]} scroll={{x:780}}/></Card>
        <Card title={<><SafetyCertificateOutlined/> 敏感情节</>}><Table size="small" rowKey={row=>`${row.episode}-${row.start}`} dataSource={sensitive} pagination={false} locale={{emptyText:'脚本文本未命中色情或暴力敏感词'}} columns={[{title:'剧集',dataIndex:'episode',width:90},{title:'时间',render:(_,row)=>`${clock(row.start)}–${clock(row.end)}`,width:110},{title:'脚本',dataIndex:'text',ellipsis:true},{title:'风险',render:(_,row)=>Object.entries(row.sensitive).map(([kind,words])=><Tag color="red" key={kind}>{kind} · {words.join('、')}</Tag>)}]} scroll={{x:650}}/></Card></div>
      </>}
    </div>}
    {tab==='clips'&&<Production embedded initialDramaId={dramaId}/>}
    {tab==='safety'&&<FinalReview dramaId={dramaId} onSaved={()=>reloadDramas(dramaId)}/>}

    <Modal title={`导入原片 · ${drama?.title??''}`} open={uploadOpen} onCancel={()=>!busy&&setUploadOpen(false)} footer={null} width={680} destroyOnHidden><Upload.Dragger directory multiple beforeUpload={()=>false} fileList={sourceFiles.map((file,index)=>({uid:`${index}-${file.name}`,name:file.webkitRelativePath||file.name,status:'done',originFileObj:file as any}))} onChange={({fileList})=>setSourceFiles(fileList.map(x=>x.originFileObj).filter(Boolean) as File[])} accept=".mp4,.mov,.mkv,.webm,.srt,.vtt,.jpg,.jpeg,.png,.webp"><p className="ant-upload-drag-icon"><FolderOpenOutlined/></p><p className="ant-upload-text">选择包含原片的文件夹</p><p className="ant-upload-hint">支持视频、字幕与剧照；文件会保存到当前剧目任务</p></Upload.Dragger>
      {sourceFiles.map(file=><div key={file.name} className="upload-file"><span>{file.webkitRelativePath||file.name}</span><Progress percent={uploadProgress[file.name]??0}/></div>)}
      {sourceFiles.length>0&&<Alert type="info" showIcon message={`已选择 ${sourceFiles.length} 个文件`} className="page-alert"/>}
      <Button block size="large" type="primary" loading={busy} disabled={!sourceFiles.length} onClick={uploadSources}>导入到剧目任务</Button>
    </Modal>
  </div>
}
