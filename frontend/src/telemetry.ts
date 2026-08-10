import { api } from './api'

type LocalEvent={client_event_id:string;feature:string;success:boolean;duration_ms:number;details:Record<string,unknown>}
const KEY='jushu:telemetry-outbox'
let flushing=false

const read=():LocalEvent[]=>{try{return JSON.parse(localStorage.getItem(KEY)||'[]')}catch{return[]}}
const write=(rows:LocalEvent[])=>localStorage.setItem(KEY,JSON.stringify(rows.slice(-1000)))

export async function flushTelemetry(){
 if(flushing||!navigator.onLine)return
 const rows=read();if(!rows.length)return
 flushing=true
 try{const batch=rows.slice(0,100);await api.sendTelemetry(batch);write(rows.slice(batch.length))}catch{/* 保留 outbox，下次联网继续 */}finally{flushing=false}
}

export function trackLocalFeature(feature:string,details:Record<string,unknown>={},success=true,durationMs=0){
 const rows=read();rows.push({client_event_id:crypto.randomUUID(),feature,success,duration_ms:durationMs,details});write(rows);void flushTelemetry()
}

window.addEventListener('online',()=>void flushTelemetry())
