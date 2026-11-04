"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Film, LockKeyhole, Mail } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export default function LoginPage(){
  const router=useRouter(); const [email,setEmail]=useState(""); const [password,setPassword]=useState(""); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  const submit=async(event:React.FormEvent)=>{event.preventDefault();setBusy(true);setError("");try{const response=await fetch(`${API}/api/auth/login`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})});if(!response.ok)throw new Error("Invalid email or password");const data=await response.json();localStorage.setItem("visualtech_token",data.access_token);localStorage.setItem("visualtech_roles",JSON.stringify(data.roles));router.push("/");}catch(e){setError(e instanceof Error?e.message:"Login failed")};setBusy(false)};
  return <main className="login-shell"><form className="login-card" onSubmit={submit}><div className="login-brand"><div><Film size={22}/></div><span>VISUALTECH</span></div><h1>Sign in to your studio</h1><p>Authorized VisualTech operators only.</p>{error&&<div className="login-error">{error}</div>}<label>Email<div><Mail size={16}/><input type="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="admin@visualtech.local"/></div></label><label>Password<div><LockKeyhole size={16}/><input type="password" required value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter password"/></div></label><button disabled={busy}>{busy?"Signing in…":"Sign in"}</button></form></main>;
}
