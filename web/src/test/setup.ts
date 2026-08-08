import "@testing-library/jest-dom/vitest";
import { toHaveNoViolations } from "jest-axe";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, expect } from "vitest";

import { server } from "./mocks";

expect.extend(toHaveNoViolations);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { cleanup(); server.resetHandlers(); });
afterAll(() => server.close());
