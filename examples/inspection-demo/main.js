import { advance } from "./simulation.js";

export function tick(positions, velocity, elapsedSeconds) {
  return positions.map((position) => advance(position, velocity, elapsedSeconds));
}
