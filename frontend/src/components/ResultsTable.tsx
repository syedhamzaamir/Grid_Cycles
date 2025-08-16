import React from "react";
export default function ResultsTable({ levels }: { levels:any[] }) {
  return <div className="card"><pre style={{overflowX:"auto"}}>{JSON.stringify(levels ?? [], null, 2)}</pre></div>;
}
