// @vitest-environment jsdom

import { forwardRef, useImperativeHandle, type ReactNode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import fixture from "./test-fixtures/mission-result-v0.json";
import type { MissionPlan } from "./types";

vi.mock("react-map-gl/maplibre", () => ({
  default: forwardRef(function MockMap(
    { children, onClick }: { children?: ReactNode; onClick?: (event: unknown) => void },
    ref,
  ) {
    useImperativeHandle(ref, () => ({ fitBounds: vi.fn() }));
    return (
      <div data-testid="maplibre-map">
        <button
          type="button"
          data-testid="mock-route-click"
          onClick={() => onClick?.({
            features: [{
              properties: {
                kind: "route",
                uav_id: "БВС 1",
                flight_index: 0,
                vpp_id: "аэродром 1",
                color: "#22d3ee",
              },
            }],
            lngLat: { lng: 37.607, lat: 55.75 },
          })}
        />
        {children}
      </div>
    );
  }),
  Source: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Layer: ({ id }: { id: string }) => <div data-testid={`layer-${id}`} />,
  Marker: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  NavigationControl: () => null,
  Popup: ({ children }: { children?: ReactNode }) => <div data-testid="route-popup">{children}</div>,
}));

import { MissionMap } from "./MissionMap";

afterEach(cleanup);

describe("MissionMap", () => {
  it("renders a feasible mission map and one legend item per UAV", () => {
    render(<MissionMap plan={fixture.mission_plan as MissionPlan} />);

    expect(screen.getByTestId("maplibre-map")).toBeTruthy();
    expect(screen.getByTestId("layer-mission-routes")).toBeTruthy();
    expect(screen.getByText("БВС 1")).toBeTruthy();
    expect(screen.getByText("БВС 2")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("shows the required empty-routes state without constructing a map", () => {
    render(<MissionMap plan={{ routes: [] }} />);

    expect(screen.getByText("Маршруты отсутствуют в результате расчёта.")).toBeTruthy();
    expect(screen.queryByTestId("maplibre-map")).toBeNull();
  });

  it("shows authoritative route identity when a route is selected", () => {
    render(<MissionMap plan={fixture.mission_plan as MissionPlan} />);

    fireEvent.click(screen.getByTestId("mock-route-click"));

    expect(screen.getByTestId("route-popup").textContent).toContain("БВС 1");
    expect(screen.getByTestId("route-popup").textContent).toContain("Вылет 0");
    expect(screen.getByTestId("route-popup").textContent).toContain("аэродром 1");
  });
});
