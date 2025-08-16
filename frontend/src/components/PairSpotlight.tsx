import React from "react";
export default function PairSpotlight({ data }: { data:any }) {
  return data ? <div className="card"><pre>{JSON.stringify(data, null, 2)}</pre></div> : null;
}
