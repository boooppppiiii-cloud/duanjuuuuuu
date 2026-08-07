import { useEffect,useState } from 'react'
import { Button,Card,Form,Image,Input,InputNumber,message,Modal,Progress,Select,Space,Spin,Switch,Table,Tag,Typography,Upload } from 'antd'
import { ArrowLeftOutlined,ExperimentOutlined,PictureOutlined,PlusOutlined,SaveOutlined } from '@ant-design/icons'
import { useNavigate,useParams } from 'react-router-dom'
import { api,Drama,EmotionWord,Highlight,HookSuggestion } from '../api'
import { coverImageSpecs,prepareCoverImage,type CoverKind,type PreparedCoverImage } from '../utils/coverImage'

const genres=['Action','Adventure','Animated','Comedy','Crime','Documentary','Drama','Family','Fantasy','Historical','Horror','Musical','Mystery','Noir','Reality','Romance','Science fiction','Sports','Thriller','Western']
const languageOptions=[
 {value:'en_US',label:'英语 · en_US'},{value:'es_LA',label:'西班牙语 · es_LA'},{value:'pt_BR',label:'葡萄牙语 · pt_BR'},
 {value:'fr_FR',label:'法语 · fr_FR'},{value:'de_DE',label:'德语 · de_DE'},{value:'id_ID',label:'印尼语 · id_ID'},
 {value:'th_TH',label:'泰语 · th_TH'},{value:'vi_VN',label:'越南语 · vi_VN'},{value:'ja_JP',label:'日语 · ja_JP'},
 {value:'ko_KR',label:'韩语 · ko_KR'},{value:'zh_CN',label:'中文 · zh_CN'},
]
const coverOptions:{kind:CoverKind;title:string;spec:string;required:boolean}[]=[
 {kind:'vertical',title:'竖版封面',spec:'3:4 · 1440×1920',required:true},
 {kind:'square',title:'方形封面',spec:'1:1 · 1200×1200',required:true},
 {kind:'horizontal',title:'横版封面',spec:'16:9 · 1920×1080',required:false},
]
const coverPath=(item:Drama,kind:CoverKind)=>kind==='vertical'?item.cover_vertical_path:kind==='square'?item.cover_square_path:item.cover_horizontal_path

export default function DramaDetail(){
 const{id=''}=useParams()
 const navigate=useNavigate()
 const[drama,setDrama]=useState<Drama>()
 const[suggestions,setSuggestions]=useState<HookSuggestion[]>([])
 const[words,setWords]=useState<EmotionWord[]>([])
 const[newWord,setNewWord]=useState('')
 const[analyzing,setAnalyzing]=useState(false)
 const[loading,setLoading]=useState(true)
 const[saving,setSaving]=useState(false)
 const[coverUploading,setCoverUploading]=useState<CoverKind>()
 const[coverPreparing,setCoverPreparing]=useState<CoverKind>()
 const[coverProgress,setCoverProgress]=useState(0)
 const[cropReview,setCropReview]=useState<(PreparedCoverImage&{kind:CoverKind;previewUrl:string})>()
 const[form]=Form.useForm()
 const[msg,context]=message.useMessage()

 const applyDrama=(data:Drama)=>{setDrama(data);form.setFieldsValue({
  title:data.title,description:data.description,total_episode_count:data.total_episode_count,promotion_episode_count:data.promotion_episode_count,
  language:data.language,genres:data.genres,actor_names:data.actor_names,source_note:data.source_note,
  is_ai_generated:data.is_ai_generated,is_dubbed_content:data.is_dubbed_content,
 })}
 const load=async()=>{try{applyDrama(await api.get(id))}catch(e){msg.error((e as Error).message)}finally{setLoading(false)}}
 const loadHooks=async()=>{const[s,w]=await Promise.all([api.hookSuggestions(Number(id)),api.emotionWords()]);setSuggestions(s);setWords(w)}
 useEffect(()=>{void load();void loadHooks().catch(e=>msg.error(e.message))},[id])
 useEffect(()=>()=>{if(cropReview?.previewUrl)URL.revokeObjectURL(cropReview.previewUrl)},[cropReview])

 const saveInfo=async(values:Record<string,unknown>)=>{if(!drama)return;setSaving(true);try{const updated=await api.update(drama.id,values);applyDrama(updated);msg.success('剧目资料已保存')}catch(e){msg.error((e as Error).message)}finally{setSaving(false)}}
 const prepareCover=async(kind:CoverKind,file:File)=>{setCoverPreparing(kind);try{const prepared=await prepareCoverImage(file,kind);setCropReview({...prepared,kind,previewUrl:URL.createObjectURL(prepared.file)})}catch(e){msg.error((e as Error).message)}finally{setCoverPreparing(undefined)}}
 const uploadCover=async(kind:CoverKind,file:File)=>{if(!drama)return false;setCoverUploading(kind);setCoverProgress(0);try{const updated=await api.uploadVideo(drama.title,'剧目任务封面（自动裁剪）',file,setCoverProgress,`cover_${kind}`);applyDrama(updated);msg.success(`${coverOptions.find(item=>item.kind===kind)?.title}已上传`);return true}catch(e){msg.error((e as Error).message);return false}finally{setCoverUploading(undefined);setCoverProgress(0)}}
 const confirmCrop=async()=>{if(cropReview&&await uploadCover(cropReview.kind,cropReview.file))setCropReview(undefined)}
 const saveHighlights=async()=>{if(!drama)return;try{setDrama(await api.highlights(drama.id,drama.highlights));msg.success('高能点已保存')}catch(e){msg.error((e as Error).message)}}
 const changeRow=(index:number,patch:Partial<Highlight>)=>setDrama(current=>current?({...current,highlights:current.highlights.map((item,row)=>row===index?{...item,...patch}:item)}):current)
 const analyze=async()=>{if(!drama)return;setAnalyzing(true);try{setSuggestions(await api.analyzeHooks(drama.id));msg.success('高能点建议已生成')}catch(e){msg.error((e as Error).message)}finally{setAnalyzing(false)}}
 const decide=async(item:HookSuggestion,action:'adopt'|'ignore')=>{try{await api.decideHook(item.id,action);await loadHooks();if(action==='adopt')await load();msg.success(action==='adopt'?'建议已采纳':'建议已忽略')}catch(e){msg.error((e as Error).message)}}

 if(loading||!drama)return <Spin fullscreen/>
 const columns=[
  {title:'剧集',render:(_:unknown,row:Highlight,index:number)=><Select value={row.episode} options={drama.episodes.map(value=>({value}))} onChange={episode=>changeRow(index,{episode})}/>},
  {title:'开始（秒）',render:(_:unknown,row:Highlight,index:number)=><InputNumber min={0} value={row.start} onChange={start=>changeRow(index,{start:start??0})}/>},
  {title:'结束（秒）',render:(_:unknown,row:Highlight,index:number)=><InputNumber min={.1} value={row.end} onChange={end=>changeRow(index,{end:end??0})}/>},
  {title:'说明',render:(_:unknown,row:Highlight,index:number)=><Input value={row.note} onChange={event=>changeRow(index,{note:event.target.value})}/>},
  {title:'',width:70,render:(_:unknown,__ :Highlight,index:number)=><Button danger type="link" onClick={()=>setDrama(current=>current?({...current,highlights:current.highlights.filter((_,row)=>row!==index)}):current)}>删除</Button>},
 ]
 const suggestionColumns=[
  {title:'剧集',dataIndex:'episode'},{title:'建议时间',render:(_:unknown,row:HookSuggestion)=>`${row.start}s – ${row.end}s`},
  {title:'依据',render:(_:unknown,row:HookSuggestion)=>row.reasons.map(reason=><Tag key={reason}>{reason}</Tag>)},{title:'状态',dataIndex:'status'},
  {title:'人工决定',render:(_:unknown,row:HookSuggestion)=><Space><Button type="primary" disabled={row.status!=='pending'} onClick={()=>decide(row,'adopt')}>采纳</Button><Button disabled={row.status!=='pending'} onClick={()=>decide(row,'ignore')}>忽略</Button></Space>},
 ]

 return <div className="workspace-page drama-detail-page">{context}
  <div className="page-heading page-heading-rich"><Space><Button icon={<ArrowLeftOutlined/>} onClick={()=>navigate('/dramas')}>返回</Button><Typography.Title level={2}>{drama.title}</Typography.Title></Space><Button type="primary" icon={<ExperimentOutlined/>} onClick={()=>navigate(`/factory?drama=${drama.id}`)}>进入内容工厂</Button></div>
  <Card title="剧目资料"><Form className="drama-detail-form" form={form} layout="vertical" onFinish={saveInfo}>
   <Form.Item name="title" label="短剧名称" rules={[{required:true,message:'请输入短剧名称'}]}><Input/></Form.Item>
   <Form.Item name="description" label="剧情简介" rules={[{required:true,message:'请输入剧情简介'}]}><Input.TextArea rows={5}/></Form.Item>
   <div className="form-grid"><Form.Item name="total_episode_count" label="总集数" rules={[{required:true}]}><InputNumber min={1} max={999} className="full-width"/></Form.Item><Form.Item name="promotion_episode_count" label="推广集数"><InputNumber min={1} max={999} className="full-width"/></Form.Item></div>
   <div className="form-grid"><Form.Item name="language" label="语种" rules={[{required:true}]}><Select showSearch optionFilterProp="label" options={languageOptions}/></Form.Item><Form.Item name="genres" label="题材分类" rules={[{required:true,message:'至少选择一种题材'}]}><Select mode="multiple" options={genres.map(value=>({value,label:value}))}/></Form.Item></div>
   <Form.Item name="actor_names" label="演员"><Select mode="tags" tokenSeparators={[',','，']} /></Form.Item>
   <Form.Item name="source_note" label="素材来源"><Input/></Form.Item>
   <div className="drama-flag-list"><Form.Item name="is_ai_generated" label="AI 标识" valuePropName="checked"><Switch checkedChildren="包含 AI" unCheckedChildren="非 AI"/></Form.Item><Form.Item name="is_dubbed_content" label="配音标识" valuePropName="checked"><Switch checkedChildren="配音内容" unCheckedChildren="原声内容"/></Form.Item></div>
   <Button size="large" type="primary" htmlType="submit" icon={<SaveOutlined/>} loading={saving}>保存剧目资料</Button>
  </Form></Card>

  <Card title="投递封面"><div className="drama-cover-list">{coverOptions.map(option=>{const path=coverPath(drama,option.kind);return <div className="drama-cover-row" key={option.kind}>
   <div className={`task-cover-preview is-${option.kind}`}>{path?<Image preview={false} src={`/api/dramas/${drama.id}/covers/${option.kind}?v=${encodeURIComponent(path)}`}/>:<PictureOutlined/>}</div>
   <div className="drama-cover-copy"><b>{option.title}</b>{!option.required&&<Tag>可选</Tag>}<span>{option.spec}</span></div>
   <div className="drama-cover-action"><Upload accept=".jpg,.jpeg,.png,.webp" showUploadList={false} beforeUpload={file=>{void prepareCover(option.kind,file);return Upload.LIST_IGNORE}} disabled={Boolean(coverUploading||coverPreparing)}><Button loading={coverUploading===option.kind||coverPreparing===option.kind}>{path?'替换并裁剪':'上传并裁剪'}</Button></Upload>{coverUploading===option.kind&&<Progress percent={coverProgress} size="small" showInfo={false}/>}</div>
  </div>})}</div></Card>

  <Card title="自动钩子建议" extra={<Button type="primary" loading={analyzing} onClick={analyze}>分析整集并生成 Top5</Button>}><Space wrap>{words.map(word=><Tag key={word.id}><Switch size="small" checked={word.enabled} onChange={enabled=>api.toggleEmotionWord(word.id,enabled).then(loadHooks)}/>{word.word}</Tag>)}<Input size="small" value={newWord} onChange={event=>setNewWord(event.target.value)} placeholder="新增情绪词" style={{width:130}}/><Button size="small" onClick={()=>api.addEmotionWord(newWord).then(()=>{setNewWord('');return loadHooks()})}>添加</Button></Space><Table rowKey="id" pagination={false} dataSource={suggestions} columns={suggestionColumns}/></Card>
  <Card title="高能点标注" extra={<Space><Button icon={<PlusOutlined/>} disabled={!drama.episodes.length} onClick={()=>setDrama({...drama,highlights:[...drama.highlights,{episode:drama.episodes[0],start:0,end:10,note:''}]})}>新增</Button><Button type="primary" onClick={saveHighlights}>保存标注</Button></Space>}><Table rowKey={(_,index)=>String(index)} pagination={false} dataSource={drama.highlights} columns={columns}/></Card>
  <Card title={`剧照墙（${drama.stills.length}）`}><Image.PreviewGroup><div className="stills-wall">{drama.stills.map(path=>{const name=path.split('/').pop()!;return <Image key={path} width={180} height={110} src={`/api/dramas/${drama.id}/stills/${encodeURIComponent(name)}`}/>})}</div></Image.PreviewGroup></Card>

  <Modal title="确认自动裁剪" open={Boolean(cropReview)} okText="确认并上传" cancelText="重新选择" onOk={()=>void confirmCrop()} onCancel={()=>!coverUploading&&setCropReview(undefined)} confirmLoading={Boolean(coverUploading)} maskClosable={!coverUploading} closable={!coverUploading} width={620}>
   {cropReview&&<div className="cover-crop-review"><div className={`cover-crop-preview is-${cropReview.kind}`}><img src={cropReview.previewUrl} alt="自动裁剪预览"/></div><div className="cover-crop-summary"><b>{coverImageSpecs[cropReview.kind].label}</b><div><span>原图</span><strong>{cropReview.sourceWidth} × {cropReview.sourceHeight}</strong></div><div><span>输出</span><strong>{cropReview.targetWidth} × {cropReview.targetHeight} JPG</strong></div><p>{cropReview.cropped?'已从画面中央裁剪到目标比例。':'原图比例已符合要求，无需裁边。'}{cropReview.resized?' 同时已转换为官方要求尺寸。':''}</p></div></div>}
  </Modal>
 </div>
}
