import React from "react";
export default function PairsChart({ pairs }: { pairs:any[] }) {
  return <div className="card"><pre style={{overflowX:"auto"}}>{JSON.stringify(pairs ?? [], null, 2)}</pre></div>;
}
