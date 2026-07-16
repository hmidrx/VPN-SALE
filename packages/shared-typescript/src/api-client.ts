export type HealthResponse = { status: string };
export async function getHealth(baseUrl: string): Promise<HealthResponse> { const r = await fetch(`${baseUrl}/health`); if (!r.ok) throw new Error("health request failed"); return r.json() as Promise<HealthResponse>; }
