export function advance(position, velocity, elapsedSeconds) {
  return position + velocity * elapsedSeconds;
}
