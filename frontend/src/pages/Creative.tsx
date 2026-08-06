import { useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Empty, Image, Input, message, Progress, Radio, Select, Space, Tag, Typography } from 'antd'
import { api, Account, Basemap, Clip, Drama, HotNote, Post, TitleCandidate } from '../api'

export default function Creative({embedded=false}:{embedded?:boolean}) {
  const [dramas, setDramas] = useState<Drama[]>([])
  const [clips, setClips] = useState<Clip[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [dramaId, setDramaId] = useState<number>()
  const [clipId, setClipId] = useState<number>()
  const [accountId, setAccountId] = useState<number>()
  const [accountType, setAccountType] = useState('official')
  const [hotNotes,setHotNotes]=useState<HotNote[]>([])
  const [selectedHot,setSelectedHot]=useState<string[]>([])
  const [language, setLanguage] = useState('English')
  const [formula, setFormula] = useState<number | 'auto'>('auto')
  const [candidates, setCandidates] = useState<TitleCandidate[]>([])
  const [titleProvider, setTitleProvider] = useState('')
  const [contextUsed, setContextUsed] = useState<string[]>([])
  const [basemaps, setBasemaps] = useState<Basemap[]>([])
  const [post, setPost] = useState<Post>()
  const [quota, setQuota] = useState<{ basemap: { used: number; limit: number }; direct: { used: number; limit: number } }>()
  const [busy, setBusy] = useState(false)
  const [msg, context] = message.useMessage()
  const drama = dramas.find(x => x.id === dramaId)

  const loadBasemaps = async (id: number) => { setBasemaps(await api.basemaps(id)); setQuota(await api.quotas()) }
  useEffect(() => { Promise.all([api.list(), api.clips(), api.quotas(), api.accounts(),api.hotNotes(true,'tiktok')]).then(([ds, cs, q, ac,hot]) => { setDramas(ds); setClips(cs); setQuota(q); setAccounts(ac); setHotNotes(hot); if (ds[0]) { setDramaId(ds[0].id); void loadBasemaps(ds[0].id) } if (cs[0]) setClipId(cs[0].id); if (ac[0]) { setAccountId(ac[0].id); setAccountType(ac[0].account_type) } }).catch(e => msg.error(e.message)) }, [])
  const changeDrama = (id: number) => { setDramaId(id); setClipId(clips.find(x => x.drama_id === id)?.id); void loadBasemaps(id) }
  const makeBasemaps = async () => { if (!drama || !drama.stills[0]) return; setBusy(true); try { await api.generateBasemaps(drama.id, drama.stills[0].split('/').pop()!); msg.success('已生成 2 版待确认底图'); await loadBasemaps(drama.id) } catch (e) { msg.error((e as Error).message) } finally { setBusy(false) } }
  const reviewMap = async (id: number, status: 'approved' | 'rejected') => { await api.reviewBasemap(id, status); if (dramaId) await loadBasemaps(dramaId) }
  const makeTitles = async () => { if (!clipId) return; setBusy(true); try { const result = await api.generateTitles(clipId, accountType, language, formula, accountId,selectedHot); setCandidates(result.candidates); setTitleProvider(result.provider); setContextUsed(result.context_used) } catch (e) { msg.error((e as Error).message) } finally { setBusy(false) } }
  const editCandidate = (index: number, patch: Partial<TitleCandidate>) => setCandidates(items => items.map((item, i) => i === index ? { ...item, ...patch } : item))
  const adopt = async (candidate: TitleCandidate) => { if (!clipId || candidate.hit_words.length) return; try { const made = await api.createPost(clipId, accountType, candidate); setPost(made); msg.success('候选已采用，可生成封面') } catch (e) { msg.error((e as Error).message) } }
  const makeCovers = async () => { if (!post) return; try { setPost(await api.createCovers(post.id, accountType)); msg.success('双规格封面已生成') } catch (e) { msg.error((e as Error).message) } }

  return <div className={embedded?'publishing-inner':'workspace-page'}>{context}{!embedded&&<Typography.Title level={2}>标题文案与封面</Typography.Title>}
    <div className="creative-grid"><Card title="一剧一底图"><Space direction="vertical" className="full-width"><Select style={{width:'100%'}} placeholder="请先选择剧目" value={dramaId} onChange={changeDrama} options={dramas.map(x => ({ value: x.id, label: x.title }))} /><div>本月底图额度：{quota?.basemap.used ?? 0}/{quota?.basemap.limit ?? 120}</div><Progress percent={Math.round(((quota?.basemap.used ?? 0) / (quota?.basemap.limit ?? 120)) * 100)} /><Button type="primary" loading={busy} disabled={!drama?.stills.length} onClick={makeBasemaps}>用首张剧照生成 2 版</Button>{!drama&&<Alert type="info" message="请先到剧库导入剧目"/>}{drama&&!drama.stills.length && <Alert type="warning" message="当前剧目没有剧照" />}</Space></Card>
      <Card title="账号与生成规则"><Space direction="vertical" className="full-width"><Select style={{width:'100%'}} aria-label="目标账号策略" placeholder="可选：应用账号策略" value={accountId} onChange={id => { setAccountId(id); const a=accounts.find(x=>x.id===id); if(a) setAccountType(a.account_type) }} options={accounts.map(x => ({ value:x.id, label:`${x.name} · 策略化` }))} /><Radio.Group value={accountType} onChange={e => setAccountType(e.target.value)} options={[{ label:'官方号',value:'official' },{ label:'达人号',value:'creator' }]} /><Typography.Text type="secondary">目标语言</Typography.Text><Input value={language} onChange={e=>setLanguage(e.target.value)} /><Select style={{width:150}} value={formula} onChange={setFormula} options={[{value:'auto',label:'自动公式'},...[1,2,3,4].map(x=>({value:x,label:`公式 ${x}`}))]} /></Space></Card></div>
    <Card title="本次文案携带热点"><Checkbox.Group value={selectedHot} onChange={v=>setSelectedHot(v as string[])} options={hotNotes.map(x=>({label:x.content,value:x.content}))}/>{hotNotes.length===0&&<Typography.Text type="secondary">当前没有未过期的 TikTok 热点</Typography.Text>}</Card>
    <Card title="AI 底图人工确认">{basemaps.length?<div className="basemap-grid">{basemaps.map(item=><div key={item.id}><Image width={260} height={150} src={`/api/creative/basemaps/${item.id}/image`} /><p><Tag color={item.status==='approved'?'green':item.status==='rejected'?'red':'gold'}>{item.status}</Tag></p><Space><Button type="primary" onClick={()=>reviewMap(item.id,'approved')}>人脸正常，批准</Button><Button danger onClick={()=>reviewMap(item.id,'rejected')}>拒绝</Button></Space></div>)}</div>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生成底图后在这里人工确认"/>}</Card>
    <Card title="每条切片生成标题"><Space wrap><Select value={clipId} onChange={setClipId} options={clips.filter(x=>!dramaId||x.drama_id===dramaId).map(x=>({value:x.id,label:`切片 #${x.id}`}))} placeholder="选择已完成切片" style={{width:200}} /><Button type="primary" disabled={!clipId} loading={busy} onClick={makeTitles}>调用模型生成 3 组候选</Button>{titleProvider&&<Tag color="green">来源：{titleProvider}</Tag>}</Space>{!clipId&&<Alert className="page-alert" type="info" showIcon message="请先在内容工厂完成至少一条切片"/>}{contextUsed.length>0&&<Alert type="success" showIcon message={`已筛选并注入：${contextUsed.join('；')}`} />}{candidates.length?<div className="candidate-grid">{candidates.map((item,index)=><Card key={index} className={item.hit_words.length?'candidate-danger':''} title={`公式 ${item.formula}`} extra={item.hit_words.map(x=><Tag color="red" key={x}>{x}</Tag>)}><Input value={item.title} onChange={e=>editCandidate(index,{title:e.target.value})} aria-label={`候选 ${index+1} 标题`} /><Input.TextArea rows={4} value={item.caption} onChange={e=>editCandidate(index,{caption:e.target.value})} aria-label={`候选 ${index+1} 文案`} /><Input value={item.hashtags.join(' ')} onChange={e=>editCandidate(index,{hashtags:e.target.value.split(/\s+/).filter(Boolean)})} aria-label={`候选 ${index+1} 标签`} /><Button type="primary" disabled={!!item.hit_words.length} onClick={()=>adopt(item)}>采用</Button></Card>)}</div>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="等待生成真实模型候选"/>}</Card>
    {post&&<Card title="封面输出"><Button type="primary" onClick={makeCovers}>压字生成 16:9 与 9:16</Button>{post.cover_path_169&&<Space className="cover-results"><Image width={320} src={`/api/creative/posts/${post.id}/cover/169`} /><Image width={180} src={`/api/creative/posts/${post.id}/cover/916`} />{post.cover_fallback&&<Tag color="orange">降级封面</Tag>}</Space>}</Card>}</div>
}
