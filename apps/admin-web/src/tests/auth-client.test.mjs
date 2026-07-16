import { readFileSync } from "node:fs";
const tokenStore = readFileSync(new URL("../auth/token-store.ts", import.meta.url), "utf8");
const apiClient = readFileSync(new URL("../auth/api-client.ts", import.meta.url), "utf8");
if (tokenStore.includes("localStorage.setItem") || tokenStore.includes("sessionStorage.setItem(\"access_token")) throw new Error("tokens must not be persisted");
if (!apiClient.includes("refreshInFlight")) throw new Error("refresh single-flight guard missing");
if (!apiClient.includes("credentials: \"include\"")) throw new Error("cookie requests must include credentials");
if (!apiClient.includes("authorization")) throw new Error("authorized requests must use Authorization header");
