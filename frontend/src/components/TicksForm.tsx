import React, { useState } from "react";
export default function TicksForm({ onRun }: { onRun: (p:any)=>void }) {
  const [symbol, setSymbol] = useState("LCID");
  const [start_ns, setStart] = useState("");
  const [end_ns, setEnd] = useState("");
  const [step, setStep] = useState("0.01");
  const [spread, setSpread] = useState("0.01");
  const [rth, setRth] = useState(true);
  return (
    <div className="card grid">
      <input placeholder="Symbol" value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())}/>
      <input placeholder="Start ns" value={start_ns} onChange={e=>setStart(e.target.value)}/>
      <input placeholder="End ns" value={end_ns} onChange={e=>setEnd(e.target.value)}/>
      <select value={step} onChange={e=>setStep(e.target.value)}><option>0.01</option><option>0.05</option></select>
      <select value={spread} onChange={e=>setSpread(e.target.value)}><option>0.01</option><option>0.05</option></select>
      <label className="row"><input type="checkbox" checked={rth} onChange={e=>setRth(e.target.checked)}/> RTH</label>
      <button className="btn" onClick={()=>onRun({symbol,start_ns,end_ns,step,spread,rth})}>Run</button>
    </div>
  );
}
