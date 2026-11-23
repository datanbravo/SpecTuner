using System.Runtime.CompilerServices;
using UnityEngine;

[assembly: InternalsVisibleTo("Assembly-CSharp-Editor")]

namespace SpecTuner.UnityDemo
{
    public enum WaypointSearchMode
    {
        Baseline,
        Optimized
    }

    internal static class NpcWorkload
    {
        internal static void Tick(
            Transform[] agents, Vector3[] waypoints, float deltaSeconds, WaypointSearchMode mode)
        {
            foreach (Transform agent in agents)
            {
                Vector3 position = agent.position;
                int closest = SelectWaypoint(position, waypoints, mode);
                agent.position = Vector3.MoveTowards(position, waypoints[closest], deltaSeconds * 2f);
            }
        }

        internal static int SelectWaypoint(Vector3 position, Vector3[] waypoints, WaypointSearchMode mode)
        {
            return mode == WaypointSearchMode.Optimized
                ? FindClosestWaypoint(position, waypoints)
                : FindClosest(MeasureWaypoints(position, waypoints));
        }

        private static int FindClosestWaypoint(Vector3 position, Vector3[] waypoints)
        {
            int closest = 0;
            float minimum = float.PositiveInfinity;
            for (int index = 0; index < waypoints.Length; index++)
            {
                float distance = Vector3.Distance(position, waypoints[index]);
                if (distance <= 0.1f || distance >= minimum)
                    continue;
                minimum = distance;
                closest = index;
            }
            return closest;
        }

        private static float[] MeasureWaypoints(Vector3 position, Vector3[] waypoints)
        {
            var distances = new float[waypoints.Length];
            for (int index = 0; index < waypoints.Length; index++)
                distances[index] = Vector3.Distance(position, waypoints[index]);
            return distances;
        }

        private static int FindClosest(float[] distances)
        {
            int closest = 0;
            float minimum = float.PositiveInfinity;
            for (int index = 0; index < distances.Length; index++)
            {
                if (distances[index] <= 0.1f || distances[index] >= minimum)
                    continue;
                minimum = distances[index];
                closest = index;
            }
            return closest;
        }
    }
}
