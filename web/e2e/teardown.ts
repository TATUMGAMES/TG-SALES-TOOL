import { execFileSync } from "node:child_process";
import path from "node:path";
import { PYTHON, ROOT } from "./helpers";

/** Stop the throwaway PostgreSQL server used by the e2e run. */
export default function teardown(): void {
  execFileSync(PYTHON, [path.join(ROOT, "tests", "e2e_server.py"), "--stop-only"], { stdio: "ignore" });
}
