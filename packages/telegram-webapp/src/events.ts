import {getNative} from "./environment";
export function registerEvent(name:string,callback:(...args:unknown[])=>void):()=>void{const app=getNative();app?.onEvent?.(name,callback);let active=true;return()=>{if(active){app?.offEvent?.(name,callback);active=false}}}
