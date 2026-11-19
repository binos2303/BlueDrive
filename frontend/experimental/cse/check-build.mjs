import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const next = fileURLToPath(new URL("../../.next/", import.meta.url));
const markers = /experimental[/\\]+cse|bluedrive-p61-|custody-worker|BlueDrive\/recovery\/approval\/v1/;
let examined = 0;
for (const scope of ["server", "static"]) {
  const root = path.join(next, scope);
  for (const name of await readdir(root, { recursive: true })) {
    if (!/\.(?:[cm]?js|json|map)$/.test(name)) continue;
    const value = await readFile(path.join(root, name), "utf8");
    if (markers.test(value)) throw new Error("Prototype emitted by production build: " + name);
    examined++;
  }
}
if (examined === 0) throw new Error("Build output unavailable");
console.log("Prototype absent from " + examined + " emitted server/static files and traces");
