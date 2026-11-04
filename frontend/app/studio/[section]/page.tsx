import { Suspense } from "react";
import StudioClient from "./studio-client";

export default function StudioPage(){
  return <Suspense fallback={<div className="studio-page"><div className="workspace-empty">Loading workspace…</div></div>}><StudioClient /></Suspense>;
}
