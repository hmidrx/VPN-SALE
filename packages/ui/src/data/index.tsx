import React from "react";
import { SearchInput } from "../forms";
export function DataTable({caption,headers,rows,rowKeys}:{caption:string;headers:string[];rows:React.ReactNode[][];rowKeys?:string[]}){return <div className="ui-table-wrap"><table className="ui-table"><caption>{caption}</caption><thead><tr>{headers.map(h=><th key={h} scope="col">{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={rowKeys?.[i]??String(i)}>{r.map((c,j)=><td key={headers[j]} data-label={headers[j]}>{c}</td>)}</tr>)}</tbody></table></div>}
export function CommandMenu({label,placeholder}:{label:string;placeholder:string}){const id=React.useId();return <form className="ui-command" role="search"><label className="ui-sr-only" htmlFor={id}>{label}</label><SearchInput id={id} placeholder={placeholder}/></form>}
