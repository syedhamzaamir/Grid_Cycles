import React from "react";
export default function BarCyclesTable({ data }: { data:any }) {
  if (!data) return <div className="card muted">No data yet.</div>;
  return <div className="card"><pre style={{overflowX:"auto"}}>{JSON.stringify(data, null, 2)}</pre></div>;
}
