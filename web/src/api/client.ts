import type { ZodType } from "zod";

export class ApiClientError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function getValidated<T>(path: string, schema: ZodType<T>): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ApiClientError("Radar could not load this data.", response.status);
  }
  return schema.parse(await response.json());
}

export async function postJson<T>(path: string, body: unknown, schema: ZodType<T>): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiClientError("Radar could not save this change.", response.status);
  return schema.parse(await response.json());
}
