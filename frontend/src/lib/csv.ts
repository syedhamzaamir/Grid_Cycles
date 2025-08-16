export function downloadCSV(filename: string, rows: { level: string; cycles: number }[]) {
  const header = "level,cycles";
  const lines = rows.map(r => `${r.level},${r.cycles}`);
  const csv = [header, ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
