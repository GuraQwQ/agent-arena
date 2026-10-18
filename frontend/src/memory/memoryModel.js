export function memoryChanges(note) {
  let oldLine = 0;
  let newLine = 0;
  const changes = [];
  for (const line of note?.changes || []) {
    if (line.kind !== "added") oldLine += 1;
    if (line.kind !== "removed") newLine += 1;
    if (line.kind !== "same" && line.text.trim()) {
      changes.push({ ...line, oldLine: line.kind === "added" ? null : oldLine,
        newLine: line.kind === "removed" ? null : newLine });
    }
  }
  return changes;
}
