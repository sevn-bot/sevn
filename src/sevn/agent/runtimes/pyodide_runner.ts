/**
 * Pyodide-in-Deno one-shot executor for sevn ``sandbox_exec`` (specs/08 §4.6).
 * Reads one JSON line from stdin: ``{ "language": "python", "code": "..." }``.
 * Writes one JSON line to stdout: ``{ "exit_code", "stdout", "stderr" }``.
 */
import { loadPyodide } from "npm:pyodide@0.26.4";

const raw = await new Response(Deno.stdin.readable).text();
const req = JSON.parse(raw) as { language?: string; code?: string };
const language = String(req.language ?? "python").toLowerCase();
const code = String(req.code ?? "");

if (language !== "python") {
  const out = { exit_code: 1, stdout: "", stderr: `unsupported language: ${language}` };
  await Deno.stdout.write(new TextEncoder().encode(JSON.stringify(out) + "\n"));
  Deno.exit(0);
}

let stdout = "";
const pyodide = await loadPyodide();
pyodide.setStdout({
  batched: (text: string) => {
    stdout += text;
  },
});

try {
  const result = await pyodide.runPythonAsync(code);
  if (result !== undefined && result !== null) {
    stdout += String(result);
    if (!stdout.endsWith("\n")) {
      stdout += "\n";
    }
  }
  const out = { exit_code: 0, stdout, stderr: "" };
  await Deno.stdout.write(new TextEncoder().encode(JSON.stringify(out) + "\n"));
} catch (err) {
  const out = {
    exit_code: 1,
    stdout,
    stderr: err instanceof Error ? err.message : String(err),
  };
  await Deno.stdout.write(new TextEncoder().encode(JSON.stringify(out) + "\n"));
}
