"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, Bell, ChevronDown, CirclePlay, Clock3, Film, FolderKanban, LayoutDashboard, Library, Menu, Plus, Search, Settings, Sparkles, WandSparkles, Tv, Zap, BarChart3, CheckCircle2 } from "lucide-react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Metric = {label:string;value:number;trend:string;tone:string};
type Project = {id:string;title:string;pillar:string;status:string;progress:number;updated:string;thumbnail:string};
type Schedule = {title:string;date:string;time:string;status:string};
type Activity = {text:string;detail:string;time:string};
type Automation = {name:string;status:string;ran:string;duration:string};
type DashboardData = {
  source:string; note:string; metrics:Metric[]; pipeline:{stage:string;count:number;color:string}[];
  recentProjects:Project[]; schedule:Schedule[]; activities:Activity[]; automation:Automation[];
};

const fallback: DashboardData = {
  source: "unavailable",
  note: "Live data unavailable. No dashboard values are displayed until the API responds.",
  metrics: [
    {label:"Total videos",value:0,trend:"",tone:"blue"},
    {label:"In production",value:0,trend:"",tone:"violet"},
    {label:"Awaiting approval",value:0,trend:"",tone:"amber"},
    {label:"Published videos",value:0,trend:"",tone:"green"},
    {label:"YouTube views",value:0,trend:"",tone:"blue"}
  ],
  pipeline: [
    {stage:"Ideas",count:0,color:"#64748b"},{stage:"Research",count:0,color:"#38bdf8"},{stage:"Script",count:0,color:"#818cf8"},{stage:"Production",count:0,color:"#a78bfa"},{stage:"Review",count:0,color:"#f59e0b"},{stage:"Approved",count:0,color:"#10b981"},{stage:"Published",count:0,color:"#3b82f6"}
  ], recentProjects: [], schedule: [], activities: [], automation: [],
};

const nav = [[LayoutDashboard,"Dashboard"],[Sparkles,"Topic Discovery"],[Search,"Research Studio"],[WandSparkles,"Script Studio"],[FolderKanban,"Storyboard"],[Library,"Media Library"],[CirclePlay,"Video Production"],[CheckCircle2,"Approvals"] ,[Tv,"YouTube & Analytics"],[Zap,"Automation"],[Settings,"Settings"]];
const colors: Record<string,string> = {blue:"metric-blue",violet:"metric-violet",amber:"metric-amber",green:"metric-green"};


export default function Dashboard() {
  const [data, setData] = useState<DashboardData>(fallback);
  const [source, setSource] = useState("loading");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const router = useRouter();
  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/dashboard`)
      .then(async r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => { setData(d); setSource(d.source || "api"); })
      .catch(() => { setData(fallback); setSource("unavailable"); setError(true); })
      .finally(() => setLoading(false));
  }, []);

  const formatNumber = (n:number) => n >= 100000 ? `${(n/1000).toFixed(1)}K` : String(n);
  return <div className="app-shell">
    <aside className={`sidebar ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <div className="brand"><div className="brand-mark"><Film size={19}/></div><div className="brand-name">VISUALTECH</div></div>
      <button className="channel"><div className="channel-avatar">VT</div><div><b>VisualTech</b><span>YouTube channel</span></div><ChevronDown size={15}/></button>
      <nav>{nav.map(([Icon,label], index) => { const I = Icon as typeof LayoutDashboard; return <button key={String(label)} className={index===0 ? "active": ""} onClick={() => { if(index===0) router.push("/"); else router.push(`/studio/${["topics","research","scripts","storyboard","media","production","approvals","youtube","automation","settings"][index-1]}`); }}><I size={18}/><span>{String(label)}</span>{label === "Approvals" && <em>{data.metrics.find(metric=>metric.label==="Awaiting approval")?.value ?? 0}</em>}</button>; })}</nav>
      <div className="sidebar-footer"><button><div className="user-avatar">PK</div><span><b>Praveen Kumar</b><small>Administrator</small></span></button></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="title-wrap"><button className="mobile-menu" onClick={() => setSidebarOpen(!sidebarOpen)}><Menu size={20}/></button><div><div className="breadcrumbs">VisualTech / <span>Dashboard</span></div><h1>Production overview</h1></div></div><div className="top-actions"><button className="icon-button"><Search size={18}/></button><button className="icon-button notification"><Bell size={18}/></button><button className="create-button" onClick={() => { window.location.href = "/studio/automation"; }}><Plus size={18}/> Create video</button></div></header>
      <div className="content">
        {loading && <div className="status-line">Connecting to VisualTech API…</div>}
        {error && <div className="warning-line">API unavailable — showing zero-value fallback data.</div>}
        {source === "database" && data.recentProjects.length === 0 && <div className="sample-label">No project data yet · {data.note}</div>}
        <section className="metrics">{data.metrics.map(m => <article className={`metric ${colors[m.tone] || "metric-blue"}`} key={m.label}><div className="metric-icon"><BarChart3 size={19}/></div><div><span>{m.label}</span><strong>{m.label.includes("views") ? formatNumber(Number(m.value)) : m.value}</strong><small>{m.trend}</small></div></article>)}</section>
        <section className="grid-3">
          <article className="panel pipeline-panel"><div className="panel-heading"><div><span>PRODUCTION PIPELINE</span><h2>Project flow</h2></div><button>View all</button></div><div className="pipeline-chart"><ResponsiveContainer width="100%" height={190}><BarChart data={data.pipeline} margin={{top:12,right:0,left:-28,bottom:0}}><XAxis dataKey="stage" tick={{fill:"#697284",fontSize:10}} axisLine={false} tickLine={false}/><YAxis tick={{fill:"#697284",fontSize:10}} axisLine={false} tickLine={false}/><Tooltip cursor={{fill:"rgba(255,255,255,.025)"}} contentStyle={{background:"#16191f",border:"1px solid #292d36",borderRadius:8,color:"#fff"}}/><Bar dataKey="count" fill="#4f7cff" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer></div><div className="pipeline-stages">{data.pipeline.map(p => <div key={p.stage}><i style={{background:p.color}}/><span>{p.stage}</span><b>{p.count}</b></div>)}</div></article>
          <article className="panel recent-panel"><div className="panel-heading"><div><span>WORK IN PROGRESS</span><h2>Recent projects</h2></div><button>View all</button></div><div className="project-list">{data.recentProjects.map((p,i)=><div className="project-row" key={p.id}><div className={`project-thumb thumb-${i}`}><Film size={18}/></div><div className="project-info"><b>{p.title}</b><span>{p.pillar}</span><div className="progress"><i style={{width:`${p.progress}%`}}/></div></div><div className="project-meta"><strong>{p.status}</strong><span>{p.updated}</span></div></div>)}</div></article>
          <article className="panel schedule-panel"><div className="panel-heading"><div><span>CALENDAR</span><h2>Publishing schedule</h2></div><button onClick={()=>router.push("/studio/youtube")}>Calendar</button></div><div className="schedule-list">{data.schedule.length ? data.schedule.map(s => <div className="schedule-row" key={s.title}><div className="date"><b>{s.date.split(" ")[0]}</b><span>{s.date.split(" ")[1]}</span></div><div><strong>{s.title}</strong><span><Clock3 size={12}/>{s.time}</span></div><em>{s.status}</em></div>) : <div className="workspace-empty">No upcoming uploads scheduled</div>}</div></article>
        </section>
        <section className="bottom-grid">
          <article className="panel quick-panel" id="quick-create"><div className="panel-heading"><div><span>START CREATING</span><h2>Quick actions</h2></div></div><div className="quick-actions"><button className="primary-action" onClick={() => { window.location.href = "/studio/automation"; }}><Plus size={20}/><div><b>Create new video</b><span>Start a production project</span></div></button><button onClick={() => { window.location.href = "/studio/topics"; }}><Sparkles size={18}/><div><b>Discover topics</b><span>Generate AI ideas</span></div></button><button onClick={() => { window.location.href = "/studio/research"; }}><Search size={18}/><div><b>Add research</b><span>Open research studio</span></div></button></div></article>
          <article className="panel activity-panel"><div className="panel-heading"><div><span>LIVE FEED</span><h2>Recent activity</h2></div></div><div className="activity-list">{data.activities.map((a)=><div key={a.text}><div><Activity size={15}/></div><p><b>{a.text}</b><span>{a.detail}</span></p><time>{a.time}</time></div>)}</div></article>
          <article className="panel automation-panel"><div className="panel-heading"><div><span>OPERATIONS</span><h2>Automation</h2></div><button>Manage</button></div><div className="automation-list">{data.automation.map(a=><div key={a.name}><i className={a.status === "Running" ? "running" : ""}/><p><b>{a.name}</b><span>{a.ran}</span></p><strong>{a.status}</strong></div>)}</div></article>
        </section>
      </div>
    </main>
  </div>;
}
