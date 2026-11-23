using UnityEngine;

namespace SpecTuner.UnityDemo
{
    internal static class NpcWorkload
    {
        internal static void Tick(Transform[] agents, Vector3[] waypoints, float deltaSeconds)
        {
            foreach (Transform agent in agents)
            {
                Vector3 position = agent.position;
                float[] distances = MeasureWaypoints(position, waypoints);
                int closest = FindClosest(distances);
                agent.position = Vector3.MoveTowards(position, waypoints[closest], deltaSeconds * 2f);
            }
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
