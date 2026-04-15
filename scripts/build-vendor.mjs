import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, "..");
const entry = resolve(projectRoot, "scripts/vendor-entry.js");
const outFile = resolve(projectRoot, "api/static/vendor/app-vendor.js");

await mkdir(dirname(outFile), { recursive: true });

await build({
  entryPoints: [entry],
  outfile: outFile,
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2020"],
  sourcemap: false,
  minify: false,
  // Иначе esbuild может выкинуть именованный export mtsLuaHighlight из entry (подсветка Lua в UI пропадает).
  treeShaking: false,
});

console.log(`Built vendor bundle: ${outFile}`);
