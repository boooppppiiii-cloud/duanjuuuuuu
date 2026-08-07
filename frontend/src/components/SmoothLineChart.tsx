import { useId,useState } from 'react'
import { Empty } from 'antd'

export type SmoothLineDetail={label:string;value:string}
export type SmoothLinePoint={label:string;axisLabel?:string;value:number;details?:SmoothLineDetail[]}

const curvePath=(points:{x:number;y:number}[])=>{
 if(!points.length)return''
 if(points.length===1)return`M ${points[0].x} ${points[0].y}`
 return points.slice(1).reduce((path,next,index)=>{
  const current=points[index]
  const middle=(current.x+next.x)/2
  return`${path} C ${middle.toFixed(2)} ${current.y.toFixed(2)}, ${middle.toFixed(2)} ${next.y.toFixed(2)}, ${next.x.toFixed(2)} ${next.y.toFixed(2)}`
 },`M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`)
}

export function SmoothLineChart({
 points,seriesName,valueFormat,axisFormat=valueFormat,ariaLabel='趋势图',emptyText='暂无趋势数据',
}:{
 points:SmoothLinePoint[];seriesName:string;valueFormat:(value:number)=>string;axisFormat?:(value:number)=>string;ariaLabel?:string;emptyText?:string
}){
 const[hovered,setHovered]=useState<number>()
 const gradientId=`smooth-fill-${useId().replace(/:/g,'')}`
 if(!points.length)return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText}/>

 const width=760,height=250,pad={left:54,right:18,top:18,bottom:34}
 const values=points.map(point=>Number.isFinite(point.value)?point.value:0)
 const minimum=Math.min(0,...values)
 const rawMaximum=Math.max(0,...values)
 const maximum=rawMaximum===minimum?minimum+1:rawMaximum
 const span=maximum-minimum
 const plotWidth=width-pad.left-pad.right
 const plotHeight=height-pad.top-pad.bottom
 const chartPoints=points.map((point,index)=>({
  ...point,
  x:pad.left+(points.length<=1 ? .5 : index/(points.length-1))*plotWidth,
  y:pad.top+(maximum-(Number.isFinite(point.value)?point.value:0))/span*plotHeight,
 }))
 const line=curvePath(chartPoints)
 const baseline=pad.top+(maximum-Math.max(0,minimum))/span*plotHeight
 const area=`${line} L ${chartPoints.at(-1)!.x.toFixed(2)} ${baseline.toFixed(2)} L ${chartPoints[0].x.toFixed(2)} ${baseline.toFixed(2)} Z`
 const ticks=[0,.25,.5,.75,1]
 const labelStep=Math.max(1,Math.ceil(points.length/5))
 const active=hovered==null?undefined:chartPoints[hovered]
 const edgeClass=active?(active.x>width-150?' is-right':active.x<pad.left+80?' is-left':'')+(active.y<80?' is-below':''):''

 return <div className="smooth-line-chart" onMouseLeave={()=>setHovered(undefined)}>
  <svg className="insight-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
   <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#CFF595" stopOpacity=".62"/><stop offset="100%" stopColor="#B1FFEC" stopOpacity=".08"/></linearGradient></defs>
   {ticks.map(tick=>{const value=minimum+span*tick;const y=pad.top+(1-tick)*plotHeight;return <g key={tick}><line x1={pad.left} x2={width-pad.right} y1={y} y2={y} className="chart-grid-line"/><text x={pad.left-9} y={y+4} textAnchor="end" className="chart-axis-label">{axisFormat(value)}</text></g>})}
   <path d={area} fill={`url(#${gradientId})`} className="chart-area"/>
   <path d={line} className="chart-line" fill="none"/>
   {active&&<line x1={active.x} x2={active.x} y1={pad.top} y2={baseline} className="chart-hover-guide"/>}
   {chartPoints.map((point,index)=>{
    const previous=chartPoints[index-1]?.x??pad.left
    const next=chartPoints[index+1]?.x??width-pad.right
    const start=index===0?pad.left:(previous+point.x)/2
    const end=index===chartPoints.length-1?width-pad.right:(point.x+next)/2
    const showLabel=index%labelStep===0||index===chartPoints.length-1
    return <g key={`${point.label}-${index}`}>
     <rect x={start} y={pad.top} width={Math.max(1,end-start)} height={plotHeight} className="chart-hover-zone" onMouseEnter={()=>setHovered(index)}/>
     <circle cx={point.x} cy={point.y} r={hovered===index?5:3} tabIndex={0} role="button" aria-label={`${point.label}，${seriesName} ${valueFormat(point.value)}`} className={`chart-point${hovered===index?' is-active':''}`} onMouseEnter={()=>setHovered(index)} onFocus={()=>setHovered(index)} onBlur={()=>setHovered(undefined)}/>
     {showLabel&&<text x={point.x} y={height-11} textAnchor={index===0?'start':index===chartPoints.length-1?'end':'middle'} className="chart-axis-label">{point.axisLabel??point.label}</text>}
    </g>
   })}
  </svg>
  {active&&<div className={`chart-detail-tooltip${edgeClass}`} style={{left:`${active.x/width*100}%`,top:`${active.y/height*100}%`}} role="status">
   <b>{active.label}</b>
   <div className="chart-tooltip-primary"><span>{seriesName}</span><strong>{valueFormat(active.value)}</strong></div>
   {!!active.details?.length&&<div className="chart-tooltip-details">{active.details.map(detail=><div key={detail.label}><span>{detail.label}</span><strong>{detail.value}</strong></div>)}</div>}
  </div>}
 </div>
}
