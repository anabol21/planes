// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App";

afterEach(cleanup);

describe("strip direction control", () => {
  it("does not render a user strip-direction field", () => {
    render(<App />);
    expect(screen.queryByText(/Направление полос/)).toBeNull();
  });
});
