export function csvCell(v) {
  if (v == null) return "";
  const s = String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function rowsToCsv(rows, columns) {
  const lines = rows.map((r) => columns.map((c) => csvCell(r[c])).join(","));
  return [columns.join(","), ...lines].join("\n") + "\n";
}

export function csvDownloadButton(label, filename, rows, columns, Inputs) {
  return Inputs.button(label, {
    reduce: () => {
      const blob = new Blob([rowsToCsv(rows, columns)], {type: "text/csv;charset=utf-8"});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    }
  });
}
