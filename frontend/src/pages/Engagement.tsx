import {
  ApiOutlined,
  BulbOutlined,
  CheckOutlined,
  CopyOutlined,
  CustomerServiceOutlined,
  FileAddOutlined,
  ReloadOutlined,
  RobotOutlined,
  SafetyOutlined,
  SendOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  Modal,
  Popconfirm,
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
import { api, type Account, type EngagementSummary, type SocialComment } from '../api'
import { PlatformBadge, PlatformLogo, PlatformLogoGroup, PlatformOption } from '../components/PlatformBrand'

const sentimentMeta:Record<string,[string,string]>={positive:['正面','green'],negative:['负面','red'],neutral:['中性','default'],unanalyzed:['待分析','orange']}
const statusMeta:Record<string,string>={pending:'待处理',following:'跟进中',resolved:'已解决',ignored:'已忽略',replied:'已回复'}
const intentMeta:Record<string,string>={potential_buyer:'追剧意向',already_purchased:'已购用户',churned:'流失风险',neutral_browser:'普通互动',dm_intent:'私信意向'}

function parseCsv(text:string){
  const rows:string[][]=[];let row:string[]=[];let cell='';let quoted=false
  for(let i=0;i<text.length;i++){const ch=text[i];if(ch==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++}else quoted=!quoted}else if(ch===','&&!quoted){row.push(cell);cell=''}else if((ch==='\n'||ch==='\r')&&!quoted){if(ch==='\r'&&text[i+1]==='\n')i++;row.push(cell);if(row.some(x=>x.trim()))rows.push(row);row=[];cell=''}else cell+=ch}
  row.push(cell);if(row.some(x=>x.trim()))rows.push(row)
  if(rows.length<2)return[]
  const headers=rows[0].map(x=>x.trim().toLowerCase())
  return rows.slice(1).map((values,index)=>{const get=(...keys:string[])=>{const pos=headers.findIndex(x=>keys.includes(x));return pos>=0?(values[pos]||'').trim():''};return{external_id:get('external_id','comment_id','id')||`import-${Date.now()}-${index}`,platform:get('platform')||'youtube',video_id:get('video_id'),video_title:get('video_title','content_title','title'),author_name:get('author_name','author'),author_handle:get('author_handle','handle'),text_original:get('text_original','comment','text'),like_count:Number(get('like_count','likes')||0),published_at:get('published_at','date')||null}}).filter(x=>x.text_original)
}

export default function Engagement({embedded=false}:{embedded?:boolean}){
  const [rows,setRows]=useState<SocialComment[]>([])
  const [accounts,setAccounts]=useState<Account[]>([])
  const [summary,setSummary]=useState<EngagementSummary>()
  const [selected,setSelected]=useState<React.Key[]>([])
  const [platform,setPlatform]=useState('all')
  const [status,setStatus]=useState('all')
  const [detail,setDetail]=useState<SocialComment>()
  const [importOpen,setImportOpen]=useState(false)
  const [syncOpen,setSyncOpen]=useState(false)
  const [syncAccounts,setSyncAccounts]=useState<number[]>([])
  const [raw,setRaw]=useState('')
  const [reply,setReply]=useState('')
  const [working,setWorking]=useState(false)
  const [msg,ctx]=message.useMessage()

  const load=async()=>{const [r,s,a]=await Promise.all([api.socialComments(),api.engagementSummary(),api.accounts()]);setRows(r);setSummary(s);setAccounts(a)}
  useEffect(()=>{load().catch(e=>msg.error(e.message))},[])
  const filtered=useMemo(()=>rows.filter(x=>(platform==='all'||x.platform===platform)&&(status==='all'||x.status===status)),[rows,platform,status])
  const connected=accounts.filter(x=>x.status==='connected'&&['youtube','facebook','instagram'].includes(x.platform))

  const analyze=async(useAi:boolean)=>{try{setWorking(true);const result=await api.analyzeComments(selected.map(Number),useAi);msg.success(useAi?`已完成 ${result.analyzed} 条真实模型分析`:`已用本地翻译与规则分析 ${result.analyzed} 条`);setSelected([]);await load()}catch(e:any){msg.error(e.message)}finally{setWorking(false)}}
  const sync=async()=>{try{setWorking(true);const r=await api.syncComments(syncAccounts,300);msg.success(`平台同步完成：新增 ${r.created}，更新 ${r.updated}`);if(r.errors.length)msg.warning(`${r.errors.length} 个账号同步失败，请查看账号连接状态`);setSyncOpen(false);await load()}catch(e:any){msg.error(e.message)}finally{setWorking(false)}}
  const submitImport=async()=>{try{let items:any[];const clean=raw.trim();if(clean.startsWith('[')||clean.startsWith('{')){const parsed=JSON.parse(clean);items=Array.isArray(parsed)?parsed:(parsed.items||[])}else items=parseCsv(clean);if(!items.length)throw new Error('没有解析到评论，请检查 CSV 表头或 JSON');const r=await api.importComments(items);msg.success(`导入完成：新增 ${r.created}，更新 ${r.updated}`);setImportOpen(false);setRaw('');await load()}catch(e:any){msg.error(e.message)}}
  const mark=async(id:number,next:string)=>{await api.setCommentStatus(id,next);await load();if(detail?.id===id)setDetail(undefined)}
  const sendReply=async()=>{if(!detail||!reply.trim())return;setWorking(true);try{const updated=await api.replyComment(detail.id,reply.trim());msg.success(`平台已返回回复 ID：${updated.reply_id}`);setReply('');setDetail(updated);await load()}catch(e:any){msg.error(e.message)}finally{setWorking(false)}}
  const openDetail=(item:SocialComment)=>{setDetail(item);setReply(item.suggested_replies[0]||'')}
  const account=detail?.account_id?accounts.find(x=>x.id===detail.account_id):undefined

  return <div className={embedded?'engagement-page engagement-embedded':'workspace-page engagement-page'}>{ctx}
    {embedded?<div className="module-toolbar"><b>粉丝互动与评论舆情</b><Space><Button icon={<FileAddOutlined/>} onClick={()=>setImportOpen(true)}>导入平台文件</Button><Button type="primary" icon={<ApiOutlined/>} onClick={()=>{setSyncAccounts(connected.map(x=>x.id));setSyncOpen(true)}}>同步评论</Button><Button icon={<ReloadOutlined/>} onClick={()=>load()}>刷新</Button></Space></div>:<div className="page-heading page-heading-rich"><Typography.Title level={2}>评论区舆情</Typography.Title><Space><Button icon={<FileAddOutlined/>} onClick={()=>setImportOpen(true)}>导入平台导出文件</Button><Button type="primary" icon={<ApiOutlined/>} onClick={()=>{setSyncAccounts(connected.map(x=>x.id));setSyncOpen(true)}}>同步官方接口</Button><Button icon={<ReloadOutlined/>} onClick={()=>load()}>刷新</Button></Space></div>}

    <div className="summary-strip engagement-summary"><Statistic title="真实评论" value={summary?.total||0}/><Statistic title="待处理" value={summary?.pending||0}/><Statistic title="需人工工单" value={summary?.needs_human||0} valueStyle={{color:'#dc2626'}}/><Statistic title="追剧 / 私信意向" value={summary?.buyer_intent||0} valueStyle={{color:'#7c3aed'}}/><Statistic title="负面评论" value={summary?.sentiment.negative||0}/><Statistic title="舆情状态" value={summary?.health==='urgent'?'紧急':summary?.health==='watch'?'关注':'健康'} valueStyle={{color:summary?.health==='urgent'?'#dc2626':summary?.health==='watch'?'#d97706':'#16a34a'}}/></div>

    <Card className="table-card" title="评论工作队列" extra={<Space wrap><Segmented value={platform} onChange={x=>setPlatform(String(x))} options={[{value:'all',label:<PlatformLogoGroup/>},...['youtube','instagram','facebook','tiktok'].map(value=>({value,label:<PlatformLogo platform={value} size={17}/>}))]}/><Select value={status} onChange={setStatus} style={{width:125}} options={[['all','全部状态'],['pending','待处理'],['following','跟进中'],['resolved','已解决'],['ignored','已忽略'],['replied','已回复']].map(([value,label])=>({value,label}))}/></Space>}>
      <div className="batch-bar"><span>已选 {selected.length} 条；未选择时处理全部待分析评论</span><Button loading={working} icon={<SafetyOutlined/>} onClick={()=>analyze(false)}>本地分级</Button><Popconfirm title="将把所选评论发送给已配置的大模型，确认继续？" onConfirm={()=>analyze(true)}><Button loading={working} type="primary" icon={<RobotOutlined/>}>AI 深度分析</Button></Popconfirm></div>
      <Table rowKey="id" rowSelection={{selectedRowKeys:selected,onChange:setSelected}} dataSource={filtered} onRow={r=>({onClick:e=>{if((e.target as HTMLElement).closest('.ant-checkbox-wrapper'))return;openDetail(r)}})} scroll={{x:1160}} locale={{emptyText:<Empty description="暂无真实评论，请连接账号同步或导入平台文件"/>}} columns={[
        {title:'平台',dataIndex:'platform',width:72,render:(x:string)=><PlatformBadge platform={x}/>},
        {title:'评论',dataIndex:'text_original',width:390,render:(x:string,r)=><div><b className="comment-author">{r.author_name||'匿名用户'}</b><p className="comment-text">{x}</p><span className="cell-sub">《{r.video_title||r.video_id||'未知内容'}》 · 👍 {r.like_count}</span></div>},
        {title:'情绪',dataIndex:'sentiment',width:90,render:(x:string)=>{const m=sentimentMeta[x]||[x,'default'];return <Tag color={m[1]}>{m[0]}</Tag>}},
        {title:'意向',dataIndex:'user_status',width:110,render:(x:string)=>intentMeta[x]||x},
        {title:'工单',width:130,render:(_:unknown,r)=>r.needs_human?<Tag color={r.severity==='high'?'red':'orange'}>{r.ticket_type}</Tag>:<Tag>无需人工</Tag>},
        {title:'摘要',dataIndex:'summary',width:230,ellipsis:true,render:(x:string)=>x||'待分析'},
        {title:'状态',dataIndex:'status',width:100,render:(x:string)=><Tag color={x==='pending'?'orange':x==='resolved'||x==='replied'?'green':'blue'}>{statusMeta[x]||x}</Tag>},
      ]}/>
    </Card>

    <Modal open={syncOpen} title="从平台官方接口同步评论" onCancel={()=>setSyncOpen(false)} onOk={sync} confirmLoading={working} okText="开始同步"><Select mode="multiple" style={{width:'100%'}} value={syncAccounts} onChange={setSyncAccounts} options={connected.map(x=>({value:x.id,label:<PlatformOption platform={x.platform} label={x.name}/>}))}/></Modal>
    <Modal open={importOpen} title="导入平台评论 CSV / JSON" onCancel={()=>setImportOpen(false)} onOk={submitImport} okText="导入"><Input.TextArea rows={12} value={raw} onChange={e=>setRaw(e.target.value)} placeholder="粘贴平台导出的 CSV 或 JSON"/></Modal>

    <Drawer open={Boolean(detail)} onClose={()=>setDetail(undefined)} width={560} title="评论详情与处理"><>{detail&&<div className="comment-detail">
      <Space><PlatformBadge platform={detail.platform}/><b>{detail.author_name||'匿名用户'}</b><span>{detail.author_handle}</span></Space><blockquote>{detail.text_original}</blockquote>
      <Card size="small" title={<><BulbOutlined/> 舆情判断</>}><p>{detail.summary||'尚未分析'}</p><Space wrap><Tag color="purple">{intentMeta[detail.user_status]||detail.user_status}</Tag><Tag>{detail.keyword_category}</Tag>{detail.keywords.map(x=><Tag key={x}>{x}</Tag>)}</Space></Card>
      <Card size="small" title={<><CustomerServiceOutlined/> 平台回复</>}>
        {detail.replied_at?<Alert type="success" showIcon message="已通过平台接口回复" description={<><p>{detail.reply_text}</p><code>{detail.reply_id}</code></>}/>:<><Input.TextArea rows={4} value={reply} onChange={e=>setReply(e.target.value)} placeholder="编辑最终回复；点击发送后将直接发布到平台"/><div className="reply-actions"><Button icon={<CopyOutlined/>} onClick={()=>navigator.clipboard.writeText(reply).then(()=>msg.success('已复制'))}>复制</Button><Popconfirm title={`确认以 ${account?.name||'关联账号'} 身份发送这条回复？`} onConfirm={sendReply}><Button type="primary" icon={<SendOutlined/>} loading={working} disabled={!account?.capabilities.includes('reply')||!reply.trim()}>确认发送到平台</Button></Popconfirm></div></>}
        {!account&&<Alert type="warning" showIcon message="导入评论未关联账号，不能直接回复；可复制后到平台处理。"/>}
      </Card>
      {detail.suggested_replies.length>0&&<Card size="small" title="模型建议（发送前必须人工编辑）">{detail.suggested_replies.map((x,i)=><div className="reply-suggestion" key={`${i}-${x}`}><span>{i+1}</span><p>{x}</p><Button type="text" icon={<CopyOutlined/>} onClick={()=>setReply(x)}/></div>)}</Card>}
      <Space wrap><Button onClick={()=>mark(detail.id,'following')}>标记跟进</Button><Button icon={<CheckOutlined/>} onClick={()=>mark(detail.id,'resolved')}>已解决</Button><Button type="text" onClick={()=>mark(detail.id,'ignored')}>忽略</Button></Space>
    </div>}</></Drawer>
  </div>
}
