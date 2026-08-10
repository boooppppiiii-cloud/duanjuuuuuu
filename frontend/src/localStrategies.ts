import type { AccountStrategy } from './api'
import { trackLocalFeature } from './telemetry'

export type LocalStrategyInput={name:string;history_text:string;confirmed:boolean}
const strategyKey=(userId:number)=>`jushu:user:${userId}:strategies`
const bindingKey=(userId:number)=>`jushu:user:${userId}:account-strategies`
const normalize=(row:Partial<AccountStrategy>&{id?:number;name?:string}):AccountStrategy=>({
 id:row.id??Date.now(),name:String(row.name||'未命名参考'),history_text:String(row.history_text||row.tone_examples||''),
 builtin:Boolean(row.builtin),confirmed:row.confirmed!==false,
})

export function getLocalStrategies(userId:number):AccountStrategy[]{
 try{const value=JSON.parse(localStorage.getItem(strategyKey(userId))||'[]');if(Array.isArray(value)){const rows=value.filter(row=>!row?.builtin).map(normalize);localStorage.setItem(strategyKey(userId),JSON.stringify(rows));return rows}}catch{/* 返回空列表 */}
 return[]
}
export function saveLocalStrategy(userId:number,payload:LocalStrategyInput,id?:number):AccountStrategy{
 const rows=getLocalStrategies(userId);const current=id?rows.find(row=>row.id===id):undefined
 const item:AccountStrategy={...payload,id:id??Date.now(),builtin:current?.builtin??false}
 const next=current?rows.map(row=>row.id===id?item:row):[...rows,item]
 localStorage.setItem(strategyKey(userId),JSON.stringify(next));trackLocalFeature(current?'本地运营策略编辑':'本地运营策略创建',{strategy_id:item.id})
 return item
}
export function getLocalBindings(userId:number):Record<string,number>{
 try{const value=JSON.parse(localStorage.getItem(bindingKey(userId))||'{}') as Record<string,number>;const valid=new Set(getLocalStrategies(userId).map(row=>row.id));const rows=Object.fromEntries(Object.entries(value).filter(([,strategyId])=>valid.has(strategyId)));localStorage.setItem(bindingKey(userId),JSON.stringify(rows));return rows}catch{return{}}
}
export function bindLocalStrategy(userId:number,accountId:number,strategyId:number){const rows=getLocalBindings(userId);rows[String(accountId)]=strategyId;localStorage.setItem(bindingKey(userId),JSON.stringify(rows));trackLocalFeature('本地账号策略绑定',{account_id:accountId,strategy_id:strategyId})}
