declare module "*.css";

declare module "jest-axe" {
  export function axe(html: HTMLElement | string): Promise<{ violations: unknown[] }>;
  export const toHaveNoViolations: Record<string, (result: unknown) => { pass: boolean; message: () => string }>;
}
